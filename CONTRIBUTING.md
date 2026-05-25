# Contributing to sandbox-skill-kit

This is the kit-internal contributor guide. If you are bringing your own
kit onto self-hosted sandboxes, see [`MIGRATING.md`](MIGRATING.md) instead.

This doc covers: setting up the dev loop, the conventions that keep CI
green and the upstream cookbook fidelity intact, and how to extend the
kit's tooling (new examples, new linter rules).

## Local dev loop

```shell
pip install -r requirements.txt -r requirements-dev.txt
```

The single command that mirrors CI:

```shell
python scripts/doctor.py            # 10 steps: ruff + pytest + check_tools + every verify + scaffold drift
python scripts/doctor.py --fix      # same, but auto-applies ruff fixes
python scripts/doctor.py -v         # also dumps PASSING step output
```

Run this **before every push**. If `doctor.py` is green locally, CI will
be green. If it is red, the failing step's full stdout/stderr is printed
inline so you can fix without re-running the underlying command.

The individual checks are also runnable on their own:

```shell
ruff check .                                            # lint kit-owned files
pytest                                                  # offline tests
python scripts/check_tools.py --strict                  # pre-flight all example tool modules
python examples/internal_data_kit/verify.py             # one example's wiring
```

## House rules

These are not stylistic preferences -- each one corresponds to a real
incident or constraint. Please follow them even when they feel verbose.

### Never `git add -A` in this repo

`setup_secret.ps1` is a local-only Windows helper that wraps the
`modal secret create` command (so PowerShell does not split a value
mid-argument; see the troubleshooting table in
[`README.md`](README.md#troubleshooting)). It is `.gitignore`d and **must
stay untracked**. `git add -A` will pick it up.

Even though the version in this repo only ever held placeholders, a real
contributor's copy is likely to contain real env keys. Always add specific
files by name.

History: commit `79f9527` (Untrack setup_secret.ps1; gitignore it).

### Keep the cookbook-derived files byte-faithful to upstream

`modal_sandbox_webhook.py` and `sandbox_runner.py` are adapted from
[anthropics/claude-cookbooks](https://github.com/anthropics/claude-cookbooks/tree/main/managed_agents/self_hosted_sandboxes/modal),
MIT-licensed and attributed in [`LICENSE`](LICENSE).

`pyproject.toml` excludes them from ruff (`extend-exclude`) and the
README "How it differs from the Anthropic cookbook" section enumerates
what this kit adds on top. **Do not refactor them for style.** Add
behaviour by:

- Adding new helper functions to those files, but leaving the existing
  ones structurally faithful to upstream.
- Adding new scripts under `scripts/` (e.g. `validate.py`, `e2e_test.py`,
  `new_example.py`, `check_tools.py`, `doctor.py`).
- Adding examples under `examples/internal_*_kit/`.

If upstream releases a newer version of the cookbook, the diff against
those two files should still be a minimal "added X for kit ergonomics".

### Tag, don't amend, when fixing a published commit

The pre-commit hook list in [`.pre-commit-config.yaml`](.pre-commit-config.yaml)
covers what doctor.py covers, just narrower. If a hook fails after a
commit looks ready, fix and create a **new** commit rather than
amending -- amending a commit that the hook bounced means the hook
never actually approved the file content you ended up with.

## Pre-commit hooks (optional but recommended)

The repo ships [`.pre-commit-config.yaml`](.pre-commit-config.yaml). After
`pip install pre-commit`, install the hooks once:

```shell
pre-commit install
```

Now every `git commit` runs: trailing-whitespace + end-of-file-fixer + YAML
/ TOML / merge-conflict / large-file checks; `ruff` with `--fix` then
`ruff-format`; `scripts/check_tools.py --strict` when any example tool
module changes; and the offline `pytest` suite. The hooks are intentionally
faster than `doctor.py` (no per-example verify, no scaffold-drift) so they
gate every commit without slowing the loop. Run `doctor.py` before pushing.

## Adding a new example template

The five existing templates (`internal_data_kit`, `internal_api_kit`,
`internal_db_kit`, `internal_queue_kit`, `internal_s3_kit`) follow the
same skeleton: an `<x>_tools.py` with two `@beta_async_tool` async
functions and a `KIT_TOOLS` export, a `sandbox_runner.py` that wires
`make_session_tools` into `worker(tools=...)`, a `verify.py` that
exercises Level-1 wiring, and a `README.md` with the "which to copy"
table.

To add a sixth pattern (e.g. `internal_grpc_kit`):

1. Copy `examples/internal_s3_kit/` (the most general factory shape) to
   `examples/internal_grpc_kit/` and rename the tools module.
2. Replace the two tools with two that exercise your pattern's surface,
   including a happy path AND at least one branch (missing/empty/error).
3. Rewrite `verify.py` to install your offline fixture (mock transport,
   in-memory store, ...) and assert the same shape the others assert.
4. Rewrite `README.md` to add the new row to the "which to copy" table.
5. Register the pattern in **all** of:
   - `scripts/new_example.py` -- add to `TEMPLATES` so the scaffold can
     produce it.
   - `scripts/check_tools.py` -- add the tools module path to
     `DEFAULT_EXAMPLE_TOOL_MODULES` so CI lints it.
   - `tests/test_examples.py` -- add a fixture + per-tool tests
     covering each branch.
   - `tests/test_scaffold.py` -- extend the `@pytest.mark.parametrize`
     list so scaffold-drift is checked on this pattern too. Add the
     module name to the template_modules tuple so leakage is caught.
   - `tests/test_check_tools.py` -- extend the `"the shipped examples
     must always lint clean"` parametrize list.
   - `.github/workflows/smoke.yml` -- add compile lines + a "Phase 2
     example verify (...)" step.
   - `README.md` Files list + "Starting a new example kit" section.
   - `MIGRATING.md` pattern-selection table.
   - `docs/rollout.md` Phase 2 references.

`python scripts/doctor.py` after each change verifies the wiring did not
break anything else. `python scripts/new_example.py test_drift --pattern
your_new --dest /tmp/xx && python /tmp/xx/test_drift/verify.py` proves the
scaffold produces a working kit.

## Adding a new check_tools rule

The linter lives in `scripts/check_tools.py` and is intentionally
AST-only -- it does not import the file under check (so it works even
when the kit's runtime deps are not installed locally). Rules currently
live in two places:

- `_check_tool_func(func)` -- per-function rules (name, async-ness,
  parameter annotations, docstring).
- `_check_kit_tools(tree, decorated_names)` -- module-level rules
  (KIT_TOOLS existence, shape, coverage).

To add a new rule:

1. Decide ERROR vs WARNING. ERROR is for things that will break the
   kit at runtime (collisions, missing schema). WARNING is for things
   that degrade the agent's tool-call quality but still run (missing
   `Args:` section, etc.).
2. Add the check in the appropriate function and append an `Issue(...)`
   with `severity`, `line`, and a message that names the tool and what
   the author should change.
3. Add tests in `tests/test_check_tools.py` mirroring the existing
   style: a `_write(tmp_path, body)` helper, then assertions via
   `_severities(issues, *needles)`. Cover both the rule firing AND not
   firing on the clean baseline.
4. Run `python scripts/check_tools.py --strict` -- the five shipped
   example kits must continue to pass clean, since they are the
   reference authors are told to copy. If your new rule flags them,
   either fix the examples or downgrade the rule's severity.

## Releases

The repo uses [SemVer](https://semver.org/) and
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

When cutting a release:

1. Move the current `## [Unreleased]` section in `CHANGELOG.md` to
   `## [X.Y.Z] - YYYY-MM-DD`, keeping the same Added/Changed/Fixed
   subsections.
2. Add an empty `## [Unreleased]` placeholder at the top for the next
   slate.
3. Commit and push the CHANGELOG change.
4. `git tag -a vX.Y.Z -m "vX.Y.Z -- see CHANGELOG.md"` then
   `git push origin vX.Y.Z`.
5. `gh release create vX.Y.Z --title "vX.Y.Z" --notes "<summary>"` with
   notes drawn from the CHANGELOG section + a pip-pin / git-clone-at-tag
   block.

`v0.1.0` (commit `8c0c07e`) and `v0.2.0` (TBD) are the templates.
