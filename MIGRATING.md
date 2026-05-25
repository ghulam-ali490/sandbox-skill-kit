# Migrating an existing kit onto self-hosted CMA sandboxes

This is the kit-author's checklist for taking a kit that already ships tools
and moving its tool execution into your own Modal sandbox using
`anthropic-sdk-python` v0.103.1's `EnvironmentWorker`.

If you are still deciding whether to adopt at all, start with
[`docs/rollout.md`](docs/rollout.md) (the "When to adopt this kit" section).
If you have decided yes, this doc is the path from "I have a tool-bearing
kit" to "those tools now run inside my Modal sandbox" with the secrets
staying on your infrastructure.

## Prerequisites

- Python 3.12+
- A Modal workspace (free Starter is enough for R&D)
- An Anthropic Claude Managed Agents environment with an `env_...` ID and an
  `sk-ant-oat-...` environment key
- Your kit's tool functions already exist as Python code (sync or async; they
  will be wrapped in `@beta_async_tool`)
- A quick read of [`SECURITY.md`](SECURITY.md) so you know what isolation
  this kit does and does not give you

## Pick the pattern that matches your tools' data source

| Your tools read from... | Pattern | Template |
| --- | --- | --- |
| A bundled file / static dataset | `data`  | [`examples/internal_data_kit`](examples/internal_data_kit) |
| A private HTTP API behind a token | `api`   | [`examples/internal_api_kit`](examples/internal_api_kit) |
| A private database (Postgres, MySQL, sqlite, ...) | `db`    | [`examples/internal_db_kit`](examples/internal_db_kit) |
| A private message queue (SQS / Redis / NATS / ...) | `queue` | [`examples/internal_queue_kit`](examples/internal_queue_kit) |
| A private object store (S3 / GCS / R2 / MinIO / ...) | `s3`    | [`examples/internal_s3_kit`](examples/internal_s3_kit) |

If your kit has tools that span more than one of these, pick the most complex
one (usually `db` or `api`) and add the simpler tools alongside; the
factory returns a flat list, so all of your tools land in one worker.

## The checklist

Tick these in order. Each step has a single concrete deliverable, and steps 1
through 7 are reachable with no Modal account and no CMA access (Level 1).

### Level 1: build it offline

- [ ] **1. Scaffold a new example kit** from the pattern you picked:
  ```shell
  python scripts/new_example.py my_kit --pattern db
  ```
  This drops a runnable copy at `examples/my_kit/` with the tool module
  renamed to `my_kit_tools.py` and all imports rewritten. Confirm it works
  immediately:
  ```shell
  cd examples/my_kit && python verify.py
  ```
  Expected tail: `PASS: ... migration wiring is correct.`

- [ ] **2. Replace the placeholder tool functions** in
  `examples/my_kit/my_kit_tools.py` with your real ones. Each tool stays a
  plain async function decorated with `@beta_async_tool`. The JSON input
  schema is inferred from your type hints and the docstring `Args` section,
  so give every parameter a type and a one-line `Args` entry. Names must not
  collide with the default toolset (`bash`, `read`, `write`, `edit`, `glob`,
  `grep`) -- the agent would silently pick whichever loaded first.

- [ ] **3. Update `KIT_TOOLS`** at the bottom of the module to list every
  tool you want exposed. The factory in `sandbox_runner.py` returns
  `[*beta_agent_toolset_20260401(ctx), *KIT_TOOLS]`, so adding a tool here
  is the only wiring change needed.

- [ ] **4. (api/db patterns only) Update the env contract.** Rename
  `INTERNAL_API_BASE_URL` / `INTERNAL_API_TOKEN` / `INTERNAL_DB_PATH` to
  match what your service expects. Keep the **injectable factory pattern**
  (`_client()` / `_conn()` with `@lru_cache`) so verify.py can swap in an
  offline fixture without touching production code paths.

- [ ] **5. Wire your offline fixture in `verify.py`.** The api template
  installs an `httpx.MockTransport`; the db template installs an in-memory
  seeded sqlite. Replace the fixture data with something representative of
  yours (a handful of records covering the happy path, a not-found case,
  and any filter branches your tools have).

  **Also update the assertions:** change `EXPECTED_CUSTOM = {...}` at the
  top of `verify.py` to your renamed tool names, and rewrite the section 3
  assertions (`if "shipped" not in str(...)` style) to check the strings
  your tools actually return. `verify.py` is intentionally strict so the
  scaffold's placeholder names don't silently bleed through after you
  rename them.

- [ ] **6a. Pre-flight your tools module** with the static linter:
  ```shell
  python scripts/check_tools.py examples/my_kit/my_kit_tools.py
  ```
  This catches the gotchas below (default-toolset name collisions, missing
  type hints, docstring/Args gaps, `KIT_TOOLS` mismatches) before you spend
  time chasing them through `verify.py` or a live session. Add `--strict`
  to fail on warnings too.

- [ ] **6b. Re-run `python verify.py`** until it prints `PASS`. The script
  asserts your tools land in the per-session factory output, that their
  input schemas are present, and that they return the strings you expect
  for each fixture input.

- [ ] **7. (Recommended) Mirror the pattern in `tests/test_examples.py`.**
  Add a per-tool pytest case per branch (happy path, missing key, filter
  edges, default args). The existing tests load example modules under
  unique `sys.modules` names via `importlib`, so collisions across kits are
  not a concern.

### Level 2: deploy to Modal

- [ ] **8. Bundle your tools module into the sandbox image.** In
  `modal_sandbox_webhook.py`, near the top alongside `_runner_src`, add:
  ```py
  _tools_src = Path(__file__).parent / "examples" / "my_kit" / "my_kit_tools.py"
  ```
  and extend `sandbox_image` with one more `add_local_file`:
  ```py
  sandbox_image = (
      modal.Image.debian_slim(python_version="3.12")
      .pip_install(SDK_PACKAGE)
      .add_local_file(_runner_src, RUNNER_PATH, copy=True)
      .add_local_file(_tools_src, "/root/my_kit_tools.py", copy=True)
  )
  ```
  If your tools need extra pip packages (e.g. `asyncpg`, `aiomysql`,
  `boto3`), add them to the `pip_install(...)` call on `sandbox_image` only
  -- the webhook image does not need them.

- [ ] **9. Point the sandbox entrypoint at your kit's runner.** Either:
  - **Easiest:** edit `RUNNER_PATH` and `_runner_src` to point at
    `examples/my_kit/sandbox_runner.py` instead of the base
    `sandbox_runner.py`, or
  - **Cleaner:** keep both, and add a second `add_local_file` so both
    runners land in the image, then change `RUNNER_PATH` to the new one.

  Either way, the file at `RUNNER_PATH` inside the sandbox is what runs.

- [ ] **10. (api/db patterns only) Add your env vars to the sandbox `env`
  dict** in `_create_sandbox`. Read them from `os.environ` (which is
  populated from the Modal Secret at container start):
  ```py
  env={
      ...,
      "INTERNAL_API_BASE_URL": os.environ["INTERNAL_API_BASE_URL"],
      "INTERNAL_API_TOKEN":    os.environ["INTERNAL_API_TOKEN"],
  }
  ```
  The credential never leaves your Modal account: it lives in the Secret,
  is mounted into the sandbox at start, and is read by your `_client()` /
  `_conn()` factory.

- [ ] **11. Set the env vars on your Modal Secret.** Use `--force` to
  replace whatever placeholder is there:
  ```shell
  modal secret create cma-self-hosted-sandboxes-secrets \
      ANTHROPIC_WEBHOOK_SECRET='whsec_...' \
      ANTHROPIC_ENVIRONMENT_ID='env_...' \
      ANTHROPIC_ENVIRONMENT_KEY='sk-ant-oat-...' \
      INTERNAL_API_BASE_URL='https://internal.your-org.example' \
      INTERNAL_API_TOKEN='...' \
      --force
  ```
  No redeploy needed for secret rotation: secrets are read at container
  start. On Windows PowerShell, see the troubleshooting table in
  [`README.md`](README.md#troubleshooting) for the wrap-safe form.

- [ ] **12. Deploy:**
  ```shell
  modal deploy modal_sandbox_webhook.py
  ```
  Modal prints a `*.modal.run` URL. Register it in the Anthropic Console
  for `session.status_run_started`, copy the returned `whsec_` into the
  Secret (step 11), and re-deploy is not needed -- the webhook re-reads on
  next request.

- [ ] **12b. Probe the deploy (optional but recommended).** Confirm the
  webhook is alive + verifying signatures BEFORE you have CMA access by
  running:
  ```shell
  export ANTHROPIC_WEBHOOK_URL='https://...modal.run'
  export ANTHROPIC_WEBHOOK_SECRET='whsec_...'
  python scripts/probe_webhook.py
  ```
  An unsigned POST should reject as 401; a signed non-`run_started` POST
  should accept as 200 with `status=ignored`. Closes the Level 2 → Level 3
  gap so you know the deploy is good before step 13.

### Level 3: prove it end to end

- [ ] **13. Run the e2e driver:**
  ```shell
  export ANTHROPIC_API_KEY=sk-ant-api...
  export ANTHROPIC_ENVIRONMENT_ID=env_...
  python scripts/e2e_test.py
  ```
  Watch the sandbox side in another terminal:
  ```shell
  modal app logs cma-self-hosted-sandboxes
  ```
  The driver creates a session, sends a user message that forces a tool
  call your kit owns, polls to `idle`/`terminated`, prints the transcript,
  and exits non-zero on any error event. PASS means an `agent.tool_use`
  event for one of your tools fired inside your Modal sandbox.

## Common gotchas

- **Tool name collisions with the default toolset.** Don't name a tool
  `bash`, `read`, `write`, `edit`, `glob`, or `grep`. The factory builds a
  flat list and the first match wins.
- **Bad docstring = bad schema.** `@beta_async_tool` infers the JSON input
  schema from type hints and the docstring `Args` section. Skipping either
  silently produces a tool the agent can't call usefully.
- **Don't pass `tools=KIT_TOOLS` directly to `worker(...)`.** You'd lose
  the default `bash`/`read`/etc. toolset and the agent couldn't even
  navigate `/workspace`. Always pass the `make_session_tools` factory.
- **Credentials path.** Always: env var on developer machine -> Modal
  Secret -> sandbox `env=` dict -> `_client()` / `_conn()` factory. Don't
  shortcut by hardcoding tokens or by reading from a file the image
  bundles.
- **Blocking drivers in async tools.** If your driver is sync (`sqlite3`,
  `psycopg2`, `requests`), wrap calls in `await asyncio.to_thread(...)` so
  the tool function's async signature isn't a lie. See
  [`examples/internal_db_kit/internal_db_tools.py`](examples/internal_db_kit/internal_db_tools.py)
  for the pattern.
- **Secret rotation.** [`SECURITY.md`](SECURITY.md) recommends rotating
  every 90 days. Use `modal secret create ... --force` -- no redeploy.
- **`modal secret list --json` shows `"Last used: -"` until the first real
  session.** Expected. Non-zero once a session hits the webhook.

## Validation gates summary

| Gate | What it proves | Needs |
| --- | --- | --- |
| **Level 0** (`python scripts/check_tools.py`) | Your tools module is free of the structural gotchas below (name collisions, missing type hints/docstrings, KIT_TOOLS issues) | Nothing beyond Python 3.12 |
| **Level 1** (`python verify.py`) | Your tools have valid schemas, land in the factory, and return correct strings against an offline fixture | Nothing beyond Python 3.12 |
| **Level 2** (`python scripts/validate.py` + `modal deploy`) | Modal is authed, the Secret exists, the SDK version is correct, the webhook is reachable | Modal account |
| **Level 2.5** (`python scripts/probe_webhook.py`) | The deployed webhook is alive AND verifying signatures correctly (unsigned → 401; signed non-`run_started` → 200 ignored) | Modal account + deployed webhook |
| **Level 3** (`python scripts/e2e_test.py`) | A real CMA session uses one of your tools inside your Modal sandbox | Modal account + CMA env + webhook registered |

Treat Level 1 as the green-light to start the deploy steps; Level 2 as the
green-light to ask Anthropic to fire a real session; Level 3 as "this
migration is done".

## When something goes wrong

- **First-run deploy / secret / webhook issues:** the troubleshooting table
  in [`README.md`](README.md#troubleshooting) covers the day-1 hits in the
  order people typically encounter them.
- **Your tool returns the wrong shape to the agent:** add a focused pytest
  case mirroring [`tests/test_examples.py`](tests/test_examples.py). It is
  much faster than chasing it through a live session.
- **The agent never calls your tool:** check the docstring `Args` section
  is present, the parameter has a type hint, and the tool's `description`
  (inferred from the docstring's first line) describes a job the agent's
  system prompt would actually ask for.
- **Your tool calls land but return secrets to the agent in error text:**
  scrub the response. The agent passes tool result strings back into the
  conversation, which is sent to Anthropic.
