"""Scaffold a new example kit from one of the five Phase 2 templates.

Usage:
    python scripts/new_example.py <kit_name> [--pattern data|api|db|queue|s3] [--dest DIR]

Copies one of the existing examples into ``<dest>/<kit_name>/``, renames the
tool module to ``<kit_name>_tools.py``, and rewrites imports + folder-name
references so the result is immediately verifiable:

    python <dest>/<kit_name>/verify.py

The author then edits the two tool functions (and, for the
api/db/queue/s3 patterns, the env var names + offline fixture) to point at
their real internal data. The Phase 2 worker wiring stays unchanged --
that is the whole point.

Patterns:
  data   Bundled JSON file (the simplest; default)
  api    Private HTTP API behind a token; ships an httpx MockTransport fixture
  db     Private database via env-configured DSN; ships an in-memory sqlite fixture
  queue  Private message queue (SQS / Redis / NATS); ships an in-memory dict fixture
  s3     Private object store (S3 / GCS / R2 / MinIO); ships an in-memory dict fixture
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

# Each template is a (source dir, current tool-module file stem) pair. The
# scaffold renames that file to ``<kit_name>_tools.py`` and updates references.
TEMPLATES = {
    "data":  {"dir": EXAMPLES / "internal_data_kit",  "tools_module": "internal_tools"},
    "api":   {"dir": EXAMPLES / "internal_api_kit",   "tools_module": "internal_api_tools"},
    "db":    {"dir": EXAMPLES / "internal_db_kit",    "tools_module": "internal_db_tools"},
    "queue": {"dir": EXAMPLES / "internal_queue_kit", "tools_module": "internal_queue_tools"},
    "s3":    {"dir": EXAMPLES / "internal_s3_kit",    "tools_module": "internal_s3_tools"},
}

# Lowercase letters / digits / underscore; must start with a letter. Same
# shape as a Python module identifier so ``<name>_tools`` is importable.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def scaffold(kit_name: str, pattern: str, dest: Path) -> Path:
    """Copy + rename a template into ``dest/kit_name``. Returns the new dir."""
    if not NAME_RE.fullmatch(kit_name):
        raise SystemExit(
            f"Invalid kit name {kit_name!r}: must match {NAME_RE.pattern} "
            "(lowercase letters, digits, underscore; start with a letter)."
        )
    if pattern not in TEMPLATES:
        raise SystemExit(
            f"Unknown pattern {pattern!r}; choose from {sorted(TEMPLATES)}."
        )

    template = TEMPLATES[pattern]
    target = dest / kit_name
    if target.exists():
        raise SystemExit(f"{target} already exists; refusing to overwrite.")

    shutil.copytree(
        template["dir"], target, ignore=shutil.ignore_patterns("__pycache__")
    )

    old_module = template["tools_module"]
    new_module = f"{kit_name}_tools"
    old_kit_dir = template["dir"].name  # e.g. internal_data_kit
    new_kit_dir = kit_name

    # 1. Rename the tool module file.
    (target / f"{old_module}.py").rename(target / f"{new_module}.py")

    # 2. Rewrite imports + kit-dir references across every file. Order matters:
    #    the module rename has to happen before the kit-dir rename because
    #    e.g. "internal_db_tools" contains "internal_db_kit"? No -- they don't
    #    overlap, but be explicit anyway so future templates stay safe.
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary asset; leave alone
        new_text = text.replace(old_module, new_module).replace(
            old_kit_dir, new_kit_dir
        )
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")

    # 3. Overwrite README.md with an adopter-focused one. The template's README
    #    is great as documentation of the canonical example, but inside a
    #    scaffolded kit it has broken relative links to the OTHER example
    #    directories, an irrelevant "which to copy" table, and a made-up
    #    scenario. Replace it with a short edit checklist.
    (target / "README.md").write_text(
        _adopter_readme(kit_name, pattern, old_kit_dir), encoding="utf-8"
    )

    # 4. Add a one-line TODO marker to the top of the tools module so the
    #    "edit this file" intent is obvious. Insert above the existing
    #    docstring; do not touch the docstring itself (the template prose is
    #    useful reference material in place).
    tools_path = target / f"{new_module}.py"
    tools_path.write_text(
        "# TODO (adopter): replace the placeholder tools below with your "
        "real ones; see README.md for the full checklist.\n"
        + tools_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    return target


_REPO_URL = "https://github.com/ghulam-ali490/sandbox-skill-kit"


def _adopter_readme(kit_name: str, pattern: str, template_dir_name: str) -> str:
    """Generate a short adopter-focused README to overwrite the template's."""
    return f"""# {kit_name}

Scaffolded from the **{pattern}** template in [sandbox-skill-kit]({_REPO_URL}).

## What to do next

1. **Edit `{kit_name}_tools.py`** -- replace the two placeholder tools with
   the ones your kit actually needs. Each must be `async def` decorated with
   `@beta_async_tool`; the docstring's `Args:` and `Returns:` sections are
   what the agent sees.
2. **Update `KIT_TOOLS`** at the bottom of the tools module to list the
   tools you want exposed.
3. **Update `verify.py`** -- change `EXPECTED_CUSTOM` to match your new
   tool names, and replace the assertions in section 3 with checks for
   your real tool I/O. (verify.py is intentionally strict so an
   uninstalled rename is caught immediately.)
4. (For api/db/queue/s3 patterns) **Update the env var names** in
   `{kit_name}_tools.py` to whatever your service expects, then mirror
   them in `sandbox_runner.py`'s `_create_sandbox` env-injection note.
5. **Pre-flight lint:**
   ```shell
   python scripts/check_tools.py path/to/{kit_name}_tools.py
   ```
6. **Run verify:** `python verify.py` from inside this directory should
   print `PASS:` once your tools, fixtures, and assertions all line up.
7. **Wire your kit into the sandbox** -- see [MIGRATING.md]({_REPO_URL}/blob/main/MIGRATING.md)
   steps 8 onwards for the `modal_sandbox_webhook.py` edits + deploy +
   Level 3 e2e test.

## About this scaffold

Pattern: `{pattern}` (one of five worked references in the upstream repo).
The original template lives at `examples/{template_dir_name}/` in
[sandbox-skill-kit]({_REPO_URL}) -- refer to its README for design rationale
and the offline-verify pattern.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new example kit from a Phase 2 template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "kit_name",
        help="Snake-case name, e.g. acme_billing (matches [a-z][a-z0-9_]*).",
    )
    parser.add_argument(
        "--pattern",
        choices=sorted(TEMPLATES),
        default="data",
        help="Which template to copy (default: data).",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=EXAMPLES,
        help=f"Destination dir for the new kit folder (default: {EXAMPLES}).",
    )
    args = parser.parse_args(argv)

    target = scaffold(args.kit_name, args.pattern, args.dest)
    print(f"Scaffolded: {target}")
    print(f"Verify it: cd {target} && python verify.py")
    print(
        "Next: see the scaffolded README.md for the full edit checklist "
        "(rename tools, update KIT_TOOLS, update verify.py assertions, etc.)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
