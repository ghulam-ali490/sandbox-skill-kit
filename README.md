# sandbox-skill-kit

Workshop R&D kit. Spin up a self-hosted sandbox for Claude Managed Agents on Modal in three commands. Uses `anthropic-sdk-python` v0.103.1 sandbox helpers (released 2026-05-19).

## What this gives you

A Modal-deployed webhook that:

1. Receives a `session.status_run_started` event from Anthropic
2. Drains the environment work queue (recovers any missed deliveries in one pass)
3. Spins up a Modal Sandbox per session that runs `client.beta.environments.work.worker(...).handle_item()`
4. Streams `bash` / `read` / `write` / `edit` / `glob` / `grep` tool calls into the sandbox, returns results to the agent
5. Auto-exits 60 seconds after `session.status_idle`

The kit isolates agent tool execution to **your infrastructure** (Modal) instead of Anthropic-managed sandboxes. Useful when tools need to see internal data, files, or services that should not leave your network.

## Architecture

```
  Anthropic CMA                          Your Modal account
  -------------                          ------------------
                                                                              
  session runs ----(1) session.status_run_started webhook---->  modal_sandbox_webhook.py
       ^                                                              |
       |                                                     (2) drain the work queue
       |                                                         (recovers missed events)
       |                                                              |
       |                                                     (3) spawn 1 Modal Sandbox
       |                                                            per session
       |                                                              |
       |                                                              v
       |                                                       sandbox_runner.py
       +----(5) tool results / final answer-----------  (4) worker().handle_item()
                                                          bash/read/write/edit/glob/grep
                                                          execute HERE, on your infra
```

The agent's reasoning stays on Anthropic; only **tool execution** is pulled into your Modal sandbox. The sandbox auto-exits ~60s after the session goes idle.

## When to use it

- You are running a workshop kit whose tools need internal data (a private DB, a workshop-only file share, an internal API)
- You want one credential (`ANTHROPIC_ENVIRONMENT_KEY`) authorising the agent runner instead of long-lived org API keys
- You are comfortable owning a Modal account for the sandbox

If your kit's tools are happy in Anthropic-managed sandboxes, you do not need this.

## Quickstart

### 1. Prerequisites

- Python 3.12+
- A Modal account (https://modal.com, free Starter plan is enough for R&D)
- An Anthropic Claude Managed Agents environment with environment ID + environment key

### 2. Install and authenticate Modal

```shell
pip install -r requirements.txt
modal setup    # one-time browser auth to your Modal workspace
```

### 3. Set Modal secrets

```shell
modal secret create cma-self-hosted-sandboxes-secrets \
    ANTHROPIC_WEBHOOK_SECRET=placeholder \
    ANTHROPIC_ENVIRONMENT_ID='env_...' \
    ANTHROPIC_ENVIRONMENT_KEY='sk-ant-oat...'
```

(Use a placeholder webhook secret for now; you swap it for the real one after the first deploy.)

### 4. Deploy

```shell
modal deploy modal_sandbox_webhook.py
```

Modal prints a `*.modal.run` URL. Register that URL as a webhook for `session.status_run_started` in the Anthropic Console (or via the API). Anthropic gives you back a `whsec_...` secret. Plug it in:

```shell
modal secret create cma-self-hosted-sandboxes-secrets \
    ANTHROPIC_WEBHOOK_SECRET='whsec_...' \
    ANTHROPIC_ENVIRONMENT_ID='env_...' \
    ANTHROPIC_ENVIRONMENT_KEY='sk-ant-oat...' \
    --force
```

No redeploy needed; secrets are read at container start.

### 5. Smoke-test

```shell
python scripts/validate.py
```

This walks through every prereq: Modal authed, secret exists, SDK version correct, environment key format matches `sk-ant-oat-`, etc. Catches the usual day-1 misconfiguration before you fire a real session.

### 6. Run a real session (Level 3 end-to-end test)

The kit ships a driver that creates a session, sends a task that forces a real
shell command inside your Modal sandbox, polls to completion, prints the
transcript, and exits non-zero on failure:

```shell
export ANTHROPIC_API_KEY=sk-ant-api...        # org key, used for session setup only
export ANTHROPIC_ENVIRONMENT_ID=env_...       # SAME env_... that is in the Modal Secret
export CMA_AGENT_ID=agt_...                    # optional; omit to auto-create a test agent
python scripts/e2e_test.py
```

In another terminal, watch the sandbox side:

```shell
modal app logs cma-self-hosted-sandboxes
```

You should see `[webhook] acked work=... session=... sandbox=sb-...` and then
`[runner] ...` lines from the sandbox itself, and the driver should end with
`PASS: agent executed tools inside the self-hosted Modal sandbox`.

Under the hood the driver does the equivalent of:

```py
import anthropic
client = anthropic.Anthropic()  # uses your org API key for THIS step only
session = client.beta.sessions.create(agent=AGENT_ID, environment_id=ENVIRONMENT_ID)
client.beta.sessions.events.send(
    session.id,
    # content is an array of content blocks, not a bare string
    events=[{"type": "user.message", "content": [{"type": "text", "text": "run `uname -a`"}]}],
)
```

## Files

- `modal_sandbox_webhook.py` — Modal app + webhook receiver + work-queue drainer + sandbox launcher
- `sandbox_runner.py` — runs inside each Modal Sandbox; one call to `EnvironmentWorker.handle_item()`
- `requirements.txt` — `anthropic[webhooks]>=0.103.1`, `modal>=0.60`, `fastapi[standard]`, `standardwebhooks`
- `.env.example` — placeholder names for local secret setup; the real values live in Modal Secrets
- `scripts/bootstrap.sh` — one-command wrapper around `modal secret create` + `modal deploy`
- `scripts/validate.py` — pre-flight sanity check (Modal authed, secret exists, SDK version, env key shape)
- `scripts/e2e_test.py` — Level 3 driver: fires a real session and asserts tools ran inside the Modal sandbox
- `scripts/new_example.py` — scaffold a new example kit from one of the three Phase 2 templates: `python scripts/new_example.py my_kit --pattern db`
- `scripts/check_tools.py` — pre-flight linter for `*_tools.py` modules: catches default-toolset name collisions, missing type hints / docstrings, KIT_TOOLS gaps. Run BEFORE `verify.py`.
- `docs/rollout.md` — when to use this kit vs Anthropic-managed sandboxes, plus a workshop-wide rollout plan
- `MIGRATING.md` — kit-author checklist: 13 ticks across Level 1 (offline), Level 2 (Modal deploy), Level 3 (live CMA), plus common gotchas and a validation-gates summary
- `examples/internal_data_kit/` — worked Phase 2 migration: tools reading a bundled dataset, wired into the worker via `tools=`, Level-1 verifiable with no CMA account
- `examples/internal_api_kit/` — second Phase 2 migration: tools calling a private HTTP API with a sandbox-only credential (the common real-world shape), verifiable offline via an httpx mock
- `examples/internal_db_kit/` — third Phase 2 migration: tools querying a private database via an env-configured DSN, verifiable offline against an in-memory seeded sqlite (swap `_conn()` for `asyncpg`/`aiomysql`/etc. to go live against a real DB)
- `tests/` — offline tests that mock the Anthropic SDK and Modal, so the webhook wiring (signature verify, queue drain, get-or-create sandbox, event routing) is exercised with **no CMA account and no Modal deploy**
- `requirements-dev.txt` — test/lint deps (`pytest`, `pytest-asyncio`, `ruff`)
- `pyproject.toml` — pytest + ruff config; cookbook-derived modules are excluded from ruff to stay byte-faithful to upstream
- `.github/workflows/smoke.yml` — CI: ruff lint, compiles sources, checks the v0.103 SDK helpers import, runs the offline tests and the example's `verify.py` (all credential-free; no Modal/CMA)

## Starting a new example kit

If you are bringing a new kit onto self-hosted sandboxes, scaffold it from one
of the Phase 2 templates instead of copying by hand:

```shell
python scripts/new_example.py my_kit --pattern db
# Scaffolded: examples/my_kit
# Verify it: cd examples/my_kit && python verify.py
```

`--pattern` picks the closest template: `data` (bundled file), `api` (private
HTTP API behind a token), or `db` (private database via env DSN). The script
copies the template, renames the tool module to `my_kit_tools.py`, and
rewrites imports so the result is immediately runnable. Then edit the two
tool functions (and, for `api`/`db`, the env var name and offline fixture)
to point at your real internal data.

For the full step-by-step from scaffold through to a live CMA session, see
[`MIGRATING.md`](MIGRATING.md).

## Development

The kit ships an offline test suite that mocks the Anthropic SDK and Modal, so
you can exercise the webhook logic with no CMA account and no deploy:

```shell
pip install -r requirements.txt -r requirements-dev.txt
ruff check .     # lint kit-owned files (cookbook modules are excluded)
pytest           # offline tests of verify / drain / get-or-create / routing
```

These are exactly the checks CI runs on every push.

## Troubleshooting

First-run issues, in roughly the order people hit them:

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError` / `validate.py` says SDK too old | anthropic < 0.103.1, the version that ships the sandbox helpers | `pip install -r requirements.txt` (pinned `>=0.103.1,<0.104`) |
| `Secret 'cma-self-hosted-sandboxes-secrets' not found` on deploy | Modal Secret never created | Run the `modal secret create ...` step above |
| On **Windows PowerShell**, `modal secret create` fails or splits a value | PowerShell wraps the multi-line backslash command mid-argument | Put it on **one line**, or define the keys in a PS array and splat them into one `modal secret create` call |
| Driver runs but **no `[webhook]` lines** in `modal app logs` | Webhook URL not registered for `session.status_run_started`, or the registered URL is stale | Re-register the `*.modal.run` URL in Console for that exact event; the drainer recovers the missed session on the next event |
| `modal secret list --json` shows `"Last used": "-"` | The secret has never been read, i.e. no session has reached the webhook yet | Expected before your first real session; non-zero once one fires |
| `401`/`403` on `sessions.create` | `ANTHROPIC_API_KEY` is a chat key or belongs to a different org than the environment | Use an **org API key from the same org** as the `env_...` |
| `validate.py` flags the env key shape | `ANTHROPIC_ENVIRONMENT_KEY` must start with `sk-ant-oat-` | Use the environment key (not an `sk-ant-api-` org key) |
| `git push` rejected with a `workflow` scope error (contributors only) | The gh token lacks the `workflow` scope needed to edit `.github/workflows/` | `gh auth refresh -h github.com -s workflow` in a real terminal (browser step needed) |

## How it differs from the Anthropic cookbook

The code in `modal_sandbox_webhook.py` and `sandbox_runner.py` is adapted from `anthropics/claude-cookbooks/managed_agents/self_hosted_sandboxes/modal/` (MIT). The kit adds:

- One-command `scripts/bootstrap.sh` so a fresh workshop kit gets to "deployed" in under five minutes
- `scripts/validate.py` pre-flight check
- `docs/rollout.md` workshop-specific guidance
- Pinned dependency versions known good with v0.103.1

If you want the unwrapped cookbook reference, https://github.com/anthropics/claude-cookbooks/tree/main/managed_agents/self_hosted_sandboxes is the source.

## Security

Tool execution runs on your infrastructure, but the model's reasoning still
runs on Anthropic and the agent gets a real shell inside the sandbox. See
[`SECURITY.md`](SECURITY.md) for what the isolation does and does not cover,
plus secret-handling and rotation guidance, before putting sensitive data
behind it.

## License

MIT (matches the upstream cookbook).
