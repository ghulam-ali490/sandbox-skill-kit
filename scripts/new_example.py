"""Scaffold a new example kit from one of the three Phase 2 templates.

Usage:
    python scripts/new_example.py <kit_name> [--pattern data|api|db] [--dest DIR]

Copies one of the existing examples into ``<dest>/<kit_name>/``, renames the
tool module to ``<kit_name>_tools.py``, and rewrites imports + folder-name
references so the result is immediately verifiable:

    python <dest>/<kit_name>/verify.py

The author then edits the two tool functions (and, for the api/db patterns,
the env var name + offline fixture) to point at their real internal data. The
Phase 2 worker wiring stays unchanged -- that is the whole point.

Patterns:
  data  Bundled JSON file (the simplest; default)
  api   Private HTTP API behind a token; ships an httpx MockTransport fixture
  db    Private database via env-configured DSN; ships an in-memory sqlite fixture
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

    return target


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
        "Next: edit the two tool functions (and, for api/db, the env var name "
        "and offline fixture) to point at your real internal data."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
