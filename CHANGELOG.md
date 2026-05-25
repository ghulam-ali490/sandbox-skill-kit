# Changelog

All notable changes to this project will be documented here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Post-v0.1 work that has shipped to `main`. Will be cut as `v0.2.0` once the
slate is stable.

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

[0.1.0]: https://github.com/ghulam-ali490/sandbox-skill-kit/releases/tag/v0.1.0
