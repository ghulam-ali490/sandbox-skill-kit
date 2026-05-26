# Changelog

All notable changes to this project will be documented here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Configurable per-sandbox timeout** -- `modal_sandbox_webhook.py` now reads
  `SANDBOX_TIMEOUT_SECONDS` from the Modal Secret instead of hardcoding 3600.
  Adopters running long agent sessions (multi-hour data processing) bump it
  without forking the cookbook code. Default is unchanged (3600). Non-integer
  or non-positive values fail loudly at first webhook delivery (a typo can't
  silently degrade to zero-second sandboxes). Documented in README "Tuning
  sandbox timeout" + `.env.example`; 7 new tests in `test_webhook_flow.py`
  cover default / valid / non-integer (4 cases) / non-positive (3 cases) /
  threaded-through-to-create.
- **`CMA_PROMPT` env var for `scripts/e2e_test.py`** -- adopters testing their
  own kit's tools can now override the default bash-exercising prompt without
  editing source. 2 new tests in `test_e2e_dry_run.py` cover default + override
  via `main()`.

### Fixed

- **Secret rotation honesty** -- both `SECURITY.md` and the README Quickstart
  previously said "no redeploy is needed" after re-creating the Modal Secret
  with `--force`. That is true for the *next* container start, but a currently-
  warm webhook container retains the old env values until it recycles. Both
  docs now document this explicitly and include the `modal app stop && modal
  deploy` recipe for forcing immediate adoption after a known-leak rotation.

## [0.3.0] - 2026-05-26

Third tagged release. Closes the long-standing "Level 3 not exercised
end-to-end" known limitation as far as is possible without Anthropic
Research Preview access (via a scripted SDK fake), ships an adopter-
experience pass + bug hunt from cold-path reviews of the kit, adds a
post-deploy webhook probe that closes the Level 2 → Level 3 gap, and a
full-system audit pass with six concrete fixes across CI, config,
scripts, and tests.

### Added

- **Level 3 dry-run** (`tests/test_e2e_dry_run.py` + a `FakeAnthropic`
  fake). Closes the v0.1 and v0.2 "Level 3 not exercised end-to-end"
  known limitation as far as is possible without Anthropic Research
  Preview access. 9 cases exercise `scripts/e2e_test.run()` against a
  scripted Anthropic SDK stub: happy path (tool_use + idle), terminated
  status also passes, auto-creates an agent when `CMA_AGENT_ID` unset,
  no-tool-use fails with the right hint, error event fails, timeout
  produces the "webhook may not be firing" hint, status transitions are
  logged once per change, and the `user.message` prompt is sent as a
  content-block list (not a bare string -- a real SDK gotcha caught by
  this test).

### Changed

- `scripts/e2e_test.py` refactored: orchestration extracted into
  `run(client, *, agent_id, environment_id, prompt, poll_seconds,
  timeout_seconds)`. `main()` is now a thin env-parsing + client-
  construction wrapper. Behaviour unchanged for live use; the refactor
  is what makes the dry-run possible.
- **Adopter-experience pass** (from an end-to-end dry-run walking the kit
  cold):
  - `scripts/new_example.py` now writes an adopter-focused `README.md`
    into each scaffolded kit instead of copying the template's verbatim.
    The old behaviour left broken relative links to `../internal_*_kit/`,
    an irrelevant "which to copy" table, and a made-up scenario; the
    new README has a 7-step "what to do next" checklist + a pointer to
    the canonical example in the upstream repo.
  - Scaffolded tools module now gets a `# TODO (adopter): replace the
    placeholder tools below ...` marker on line 1 so the edit intent is
    obvious on open.
  - README `## Quickstart` gains a final step 7 telling adopters that
    steps 1-6 deploy the base kit only and they need to follow
    `MIGRATING.md` to wire their own tools.
  - `MIGRATING.md` step 5 now explicitly tells adopters to update
    `EXPECTED_CUSTOM` and the section-3 assertions in `verify.py` when
    they rename tools (previously the doc only mentioned the offline
    fixture).
  - `tests/test_scaffold.py` asserts the new adopter README shape +
    the TODO marker presence.

- `scripts/probe_webhook.py` -- closes the Level 2 → Level 3 gap. After
  `modal deploy`, run `python scripts/probe_webhook.py` (with
  `ANTHROPIC_WEBHOOK_URL` + optional `ANTHROPIC_WEBHOOK_SECRET` in env)
  to confirm the webhook is alive + verifying signatures, WITHOUT
  needing Anthropic Research Preview access. Two probes: unsigned POST
  → expect 401 (reachable + signing enforced); signed non-`run_started`
  POST → expect 200 with `status=ignored` (signature verification works
  end-to-end). Uses `httpx` + `standardwebhooks`, both already kit deps.
  12 tests cover both probes' pass / fail / network-error / 401 / wrong
  shape paths, plus a round-trip that signs with `_build_signed_headers`
  and verifies under `standardwebhooks.Webhook` to catch any
  off-by-one or wrong-field bug. README adds step 5b; MIGRATING adds
  step 12b + a new "Level 2.5" row in the validation gates table.

### Fixed

- **Full-system audit pass** (a systematic re-audit across 6 dimensions:
  inventory, code correctness, docs-vs-reality, link integrity, test
  coverage, dependency/config):
  - `.github/workflows/smoke.yml` `Compile all Python sources` step was
    missing `scripts/doctor.py` and `scripts/probe_webhook.py` (both
    added post-v0.2). Syntax errors in those two scripts would have
    been caught only via the test imports, not directly. Now listed.
  - `pyproject.toml` `[tool.ruff] extend-exclude` listed
    `examples/internal_data_kit/sandbox_runner.py` but not the four
    other example runners. Investigated: all 5 example runners pass
    ruff cleanly at project level (the false positive comes from
    single-file checks where ruff lacks project context). The
    `internal_data_kit` exclude was vestigial; removed for honesty.
    Updated the comment to explain the remaining two excludes
    (cookbook-derived modules only).
  - `scripts/new_example.py` module docstring said "three Phase 2
    templates" and its `Patterns:` section listed only data/api/db --
    stale since v0.2 added queue + s3. Docstring + usage + final
    `print` updated to mention all 5; final print also de-duplicates
    the README's edit checklist.
  - `scripts/probe_webhook.py` error message referenced "bug B4 makes
    pre-v0.3 reject UTF-8 as 500" -- misleading, since B4 was about
    NON-UTF-8 (decode failure) and a signed probe sends valid UTF-8
    JSON. Reworded the hint to focus on the actual likely cause
    (secret mismatch).
  - `scripts/doctor.py` `_scaffold_drift_steps()` created a tmp dir
    via `tempfile.mkdtemp` and never cleaned it up; repeated doctor
    runs accumulated `doctor_scaffold_*` dirs in `TMPDIR`. Added
    `atexit.register(shutil.rmtree, tmp, True)` so the dir is removed
    on process exit (ignore_errors so a partial run can't crash
    teardown).
  - `tests/test_validate.py` (17 new tests) -- `scripts/validate.py`
    had no dedicated test coverage despite being adopter-facing and
    branching on multiple failure paths per check. Mocks
    `importlib.import_module` and `subprocess.run` to exercise each
    branch: SDK pass / missing / too-old / broken-install; Modal auth
    pass / not-authed / CLI-missing / timeout; secret present / absent
    / command-failed / unparseable-JSON; env key absent (non-fatal) /
    correct-prefix / wrong-prefix (the common "pasted org API key"
    slip); `main()` aggregation.
  - Markdown link integrity: 12 .md files, all internal links resolve.
    Audited via a small helper script.

- **Bug hunt pass** (from a critical-eye read of every kit-owned file):
  - `modal_sandbox_webhook.py` `_verify_webhook` now catches
    `UnicodeDecodeError` alongside the existing signature-failure
    exceptions. Adversarial non-UTF-8 webhook bodies previously crashed
    the handler with a 500 (leaking "the server crashed handling this");
    they now reject as 401 like any other bad delivery. Regression test
    `test_verify_webhook_non_utf8_body_raises_401` in
    `tests/test_webhook_flow.py`.
  - `modal_sandbox_webhook.py` `_drain_work` now returns skipped
    (non-session) work items in its result list with `skipped=True`, so
    operators can see "I skipped N non-session items" instead of having
    to grep the logs. Also documents WHY processing is serial (TOCTOU
    on `_find_live_sandbox` for duplicate session_id under redelivery /
    retry).
  - `scripts/validate.py` had a `REQUIRED_KEYS` constant and a docstring
    claim that the secret's contents were checked. Modal's CLI does not
    expose secret contents, so the check was impossible to implement.
    Removed the dead constant; updated the docstring to be honest about
    what is actually checked.
  - `scripts/bootstrap.sh` previously ran `python scripts/validate.py
    || { print 'ignore that failure' }`, which silently swallowed real
    failures (SDK missing, modal not authed) alongside the expected
    "secret does not exist yet" failure on first run. Now runs only the
    pre-secret checks (SDK + Modal auth + env key shape) and HALTS on
    those failures; the secret-exists check is deferred to the post-
    deploy `python scripts/validate.py` run.

## [0.2.0] - 2026-05-25

Second tagged release. Extends the example pattern catalogue to five
(adds queue + S3), ships kit-author tooling (`scripts/doctor.py`,
`.pre-commit-config.yaml`, `CONTRIBUTING.md`), tightens the pre-flight
linter (closes the v0.1 aliased-decorator limitation; adds snake_case /
return-type / `Returns:` rules), and updates all docs.

### Added

- `examples/internal_queue_kit/` -- fourth Phase 2 example. Message-queue
  pattern (SQS / Redis Streams / NATS / RabbitMQ / ...). Env contract
  `INTERNAL_QUEUE_URL`; offline-verifiable against a seeded in-memory
  `dict[channel, list[job]]`. Swap `_store()` for an async queue client to
  go live. Wired into `scripts/new_example.py` (`--pattern queue`),
  `scripts/check_tools.py` default scan list, `tests/test_examples.py`,
  `tests/test_scaffold.py`, `tests/test_check_tools.py`, CI smoke, and the
  README / MIGRATING.md / docs/rollout.md pattern tables.
- `scripts/doctor.py` -- one-command local health check. Runs ruff, pytest,
  `check_tools.py --strict`, every example's `verify.py`, and the
  scaffold-drift check in order with per-step PASS/FAIL + final tally.
  `--fix` promotes the ruff step to `ruff check . --fix`. 8 tests cover
  the `run_step` / `run_steps` primitives and the canonical step shape;
  the script is intentionally NOT run from CI (CI already runs each
  underlying check individually) but is the recommended pre-push gate
  for contributors.
- `.pre-commit-config.yaml` -- optional pre-commit hooks (install once
  with `pre-commit install`). Runs trailing-whitespace + end-of-file-fixer
  + YAML/TOML/merge-conflict/large-file checks, `ruff --fix`, `ruff-format`,
  `check_tools.py --strict` (when any example tool module changes), and
  the offline `pytest` suite. Faster than `doctor.py` so it gates every
  commit; use `doctor.py` before pushing.
- `CONTRIBUTING.md` -- kit-internal contributor guide (distinct from
  `MIGRATING.md` which is for adopters). Covers the local dev loop
  (`scripts/doctor.py` is the gate), house rules (no `git add -A`,
  cookbook fidelity), the checklist for adding a new example template
  (touches `new_example.py` + `check_tools.py` + three test files +
  CI + three docs), the checklist for adding a new `check_tools` rule,
  and the release procedure.
- `examples/internal_s3_kit/` -- fifth Phase 2 example. Object-store
  pattern (S3 / GCS / Cloudflare R2 / self-hosted MinIO / ...). Env
  contract `INTERNAL_S3_BUCKET` + `INTERNAL_S3_REGION` +
  `INTERNAL_S3_ACCESS_KEY` + `INTERNAL_S3_SECRET_KEY`; offline-verifiable
  against a seeded in-memory `dict[key, metadata]`. Swap `_bucket()` for
  an async S3 client (`aiobotocore` / `aioboto3`) to go live. Wired into
  `scripts/new_example.py` (`--pattern s3`), `scripts/check_tools.py`
  default scan list, `tests/test_examples.py`, `tests/test_scaffold.py`,
  `tests/test_check_tools.py`, CI smoke, and the README / MIGRATING.md /
  docs/rollout.md pattern tables.

### Changed

- `scripts/check_tools.py` now tracks `from ... import beta_async_tool as X`
  aliased imports and recognises `@X` as a tool decorator. Closes the v0.1
  "decorator detection" limitation. New tests cover bare/aliased/short-alias/
  multiple-aliases paths and confirm an unrelated import aliased to the
  same local name is not treated as a kit tool.
- `scripts/check_tools.py` gains three new rules (all WARNING so existing
  kits keep working before they catch up): tool name must be `snake_case`;
  tool function should have a return-type annotation; docstring should
  include a `Returns:` section so the agent knows the shape of the response.
  All five shipped examples were updated with `Returns:` sections so they
  continue to pass `--strict` and remain valid copy targets.

## [0.1.0] - 2026-05-25

First tagged release. The kit is feature-complete for adopting `anthropic-sdk-python`
v0.103.1 self-hosted CMA sandboxes on Modal, with worked examples, scaffolding,
linting, and a documented migration path.

### Core (the kit itself)

- `modal_sandbox_webhook.py` -- FastAPI webhook on Modal that drains the
  environment work queue and spawns one Modal Sandbox per session. Adapted
  from the Anthropic cookbook reference (kept byte-faithful, MIT-attributed
  in `LICENSE`).
- `sandbox_runner.py` -- runs inside each sandbox; one call to
  `client.beta.environments.work.worker(...).handle_item()`.
- `requirements.txt` -- pinned `anthropic[webhooks]>=0.103.1,<0.104`,
  `modal>=0.60`, `fastapi[standard]>=0.110`, `standardwebhooks>=1.0`.
- One-command bootstrap (`scripts/bootstrap.sh`) and pre-flight check
  (`scripts/validate.py`) covering Modal auth, secret presence, SDK version,
  and `sk-ant-oat-` env key shape.

### Phase 2 examples (three patterns)

Three worked migration references, each runnable offline (Level 1) with no
CMA account and no Modal deploy. All three use the same one-line migration:
keep `worker()`, pass a `tools=` factory.

- `examples/internal_data_kit/` -- tools reading a bundled JSON file.
- `examples/internal_api_kit/` -- tools calling a private HTTP API with a
  sandbox-only credential; offline-verifiable via an `httpx.MockTransport`.
- `examples/internal_db_kit/` -- tools querying a private database via an
  env-configured DSN; offline-verifiable against an in-memory seeded sqlite
  (`asyncio.to_thread` wrapper for sync drivers). Swap `_conn()` for
  `asyncpg`/`aiomysql` to target a real database; the worker wiring is
  unchanged.

### Author tooling

- `scripts/new_example.py` -- scaffolds a new example kit from any of the
  three templates: `python scripts/new_example.py my_kit --pattern db`.
  Validates name as `[a-z][a-z0-9_]*`, refuses to overwrite, rejects unknown
  patterns. Result is immediately runnable.
- `scripts/check_tools.py` -- AST-based pre-flight linter for `*_tools.py`.
  Catches default-toolset name collisions (`bash`/`read`/etc.), sync
  functions decorated with `@beta_async_tool`, missing parameter type hints,
  missing docstring / Args section, and `KIT_TOOLS` shape/coverage issues.
  ERROR vs WARNING severities; `--strict` promotes warnings. No imports, so
  it works even when runtime deps (`asyncpg`, ...) aren't installed.

### Validation gates (Level 0 through 3)

- **Level 0** (`scripts/check_tools.py`) -- structural lint on the tools
  module.
- **Level 1** (per-example `verify.py` + `tests/`) -- factory output, tool
  schemas, tool return shapes against offline fixtures.
- **Level 2** (`scripts/validate.py` + `modal deploy`) -- Modal authed, the
  Secret exists, SDK version correct, webhook reachable.
- **Level 3** (`scripts/e2e_test.py`) -- live CMA session uses one of the
  kit's tools inside the Modal sandbox; asserts on `agent.tool_use` events
  and the absence of error events.

### Documentation

- `MIGRATING.md` -- 13-tick checklist for moving an existing kit onto
  self-hosted sandboxes, organised around the four validation gates above.
  Pattern-selection table, copy-pasteable `modal_sandbox_webhook.py`
  edits, common gotchas (default-toolset collisions, blocking drivers,
  credentials path), validation-gates summary.
- `SECURITY.md` -- threat model: what the sandbox isolates (tool execution
  on your infra) and what it does not (reasoning still on Anthropic, agent
  gets a real shell, per-session volumes not a full multi-tenant boundary).
  Secret handling guidance + 90-day rotation cadence.
- `docs/rollout.md` -- when-to-adopt criteria, host-comparison matrix
  (Modal chosen vs Docker / Cloudflare Containers / Cloudflare Workers /
  Vercel / Daytona), four-phase rollout plan, cost notes.
- `README.md` -- quickstart (5 numbered steps from `pip install` to a live
  session), architecture diagram, troubleshooting table (8 rows covering
  Windows PowerShell secret-wrap, webhook-not-firing, env-key shape, gh
  workflow scope, etc.), "Starting a new example kit" section.

### Testing and CI

- `tests/` (52 cases total):
  - `test_webhook_flow.py` (11) -- offline coverage of `_verify_webhook`,
    `_process_work_item`, `_drain_work`, and webhook endpoint routing, with
    the Anthropic SDK and Modal fully mocked.
  - `test_examples.py` (16) -- per-tool direct tests for all three example
    kits, including null/missing/empty/filter branches the `verify.py`
    smoke scripts only spot-check. Example modules are loaded by path
    under unique `sys.modules` names so the three `sandbox_runner.py`
    files don't collide.
  - `test_scaffold.py` (6) -- parametrised over data/api/db: scaffold into
    `tmp_path`, assert structure + import rewriting, load and exercise
    the scaffolded tool module. Plus overwrite/bad-name/unknown-pattern
    rejection paths.
  - `test_check_tools.py` (19) -- one synth tool module per linter rule,
    syntax-error + missing-file paths, CLI exit codes, `--strict` mode,
    and a parametrised "the three shipped examples must always lint clean"
    baseline.
- `.github/workflows/smoke.yml` -- on every push: ruff lint, compile all
  Python sources, SDK helper-import check, full pytest, `check_tools.py
  --strict`, every example's `verify.py`, and a "scaffold + verify a fresh
  kit" step that catches template drift.
- `pyproject.toml` -- pytest (`asyncio_mode=auto`, `pythonpath=["."]`) and
  ruff config (`select=E,F,I,B,UP`, line-length 100). Cookbook-derived
  modules are excluded from ruff to stay byte-faithful to upstream.
- Pre-commit incident note (commit 79f9527): never `git add -A` --
  `setup_secret.ps1` is a local-only Windows helper and must stay
  untracked.

### Known limitations

- **Level 3 has not been run end-to-end against a real CMA environment in
  this release.** Access is gated by the Anthropic Research Preview
  waitlist (`https://claude.com/form/claude-managed-agents`). The driver
  (`scripts/e2e_test.py`) is built and unit-tested; Levels 0, 1, and 2 are
  fully exercised on every push.
- `scripts/check_tools.py` only recognises `@beta_async_tool` when it
  appears under that bare name (or attribute access ending in it). Aliased
  imports like `from anthropic.lib.tools import beta_async_tool as t` are
  not tracked.
- MCP tunnels are out of scope for v0.1 (Phase 4 of the rollout plan).
  They are a separate Research Preview feature gated independently.

[0.3.0]: https://github.com/ghulam-ali490/sandbox-skill-kit/releases/tag/v0.3.0
[0.2.0]: https://github.com/ghulam-ali490/sandbox-skill-kit/releases/tag/v0.2.0
[0.1.0]: https://github.com/ghulam-ali490/sandbox-skill-kit/releases/tag/v0.1.0
