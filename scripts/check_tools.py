"""Pre-flight linter for kit tool modules.

Catches the MIGRATING.md "Common gotchas" against a ``*_tools.py`` file
statically (AST-only, no import) so an author sees them before running
``verify.py``. Rules checked:

  - Tool names that collide with the default agent toolset
    (`bash`/`read`/`write`/`edit`/`glob`/`grep`). The factory builds a flat
    list -- whichever name lands first wins, your tool stays dark.
  - Tool functions decorated with ``@beta_async_tool`` that are NOT async.
    The decorator wraps async functions; sync ones are silently broken.
  - Tool parameters missing a type annotation. The decorator infers the
    JSON input schema from type hints.
  - Missing docstring or missing ``Args:`` section. The decorator infers the
    tool description from the docstring and parameter descriptions from the
    Args block.
  - Missing or empty ``KIT_TOOLS`` export.
  - ``KIT_TOOLS`` entries that don't reference a decorated tool in this
    file, or decorated tools that aren't in ``KIT_TOOLS`` (orphans the
    agent will never see).

Limitation: detects ``@beta_async_tool`` only when referenced by that bare
name (or as an attribute access ending in ``beta_async_tool``). Aliased
imports like ``from anthropic.lib.tools import beta_async_tool as tool``
are not tracked.

Usage:
    python scripts/check_tools.py                       # scan all example tool modules
    python scripts/check_tools.py path/to/my_tools.py   # one or more paths
    python scripts/check_tools.py --strict ...          # warnings count as errors

Exit code: 0 if clean, 1 if any ERROR found (or any WARNING in --strict).
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

DEFAULT_EXAMPLE_TOOL_MODULES = [
    EXAMPLES / "internal_data_kit"  / "internal_tools.py",
    EXAMPLES / "internal_api_kit"   / "internal_api_tools.py",
    EXAMPLES / "internal_db_kit"    / "internal_db_tools.py",
    EXAMPLES / "internal_queue_kit" / "internal_queue_tools.py",
]

# Names exposed by ``beta_agent_toolset_20260401(ctx)``. A collision means
# the agent picks whichever loaded first, so your tool stays unused.
DEFAULT_TOOL_NAMES = frozenset({"bash", "read", "write", "edit", "glob", "grep"})

# Decorator names we recognise as marking a tool.
TOOL_DECORATORS = frozenset({"beta_async_tool"})


@dataclass(frozen=True)
class Issue:
    severity: str  # "ERROR" or "WARNING"
    line: int
    message: str


def _decorator_name(node: ast.expr) -> str | None:
    """Return the trailing identifier of a decorator expression."""
    while isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _has_args_section(docstring: str | None) -> bool:
    if not docstring:
        return False
    return any(line.strip() == "Args:" for line in docstring.splitlines())


def _check_tool_func(func: ast.AsyncFunctionDef | ast.FunctionDef) -> list[Issue]:
    issues: list[Issue] = []
    name = func.name

    if name in DEFAULT_TOOL_NAMES:
        issues.append(
            Issue(
                "ERROR",
                func.lineno,
                f"tool '{name}' collides with the default toolset name "
                f"'{name}' -- rename it (default tools: "
                f"{', '.join(sorted(DEFAULT_TOOL_NAMES))}).",
            )
        )

    if isinstance(func, ast.FunctionDef):
        issues.append(
            Issue(
                "ERROR",
                func.lineno,
                f"tool '{name}' must be 'async def' (the @beta_async_tool "
                "decorator wraps async functions).",
            )
        )

    for arg in func.args.args:
        if arg.annotation is None:
            issues.append(
                Issue(
                    "ERROR",
                    arg.lineno,
                    f"tool '{name}': parameter '{arg.arg}' is missing a "
                    "type annotation (used to infer the JSON input schema).",
                )
            )

    docstring = ast.get_docstring(func)
    has_params = bool(func.args.args)
    if not docstring:
        issues.append(
            Issue(
                "ERROR" if has_params else "WARNING",
                func.lineno,
                f"tool '{name}' has no docstring (used by the decorator for "
                "the tool description and parameter descriptions).",
            )
        )
    elif has_params and not _has_args_section(docstring):
        issues.append(
            Issue(
                "WARNING",
                func.lineno,
                f"tool '{name}' docstring has no 'Args:' section; "
                "parameter descriptions will be empty in the schema.",
            )
        )

    return issues


def _check_kit_tools(tree: ast.Module, decorated_names: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    kit_tools_node: ast.Assign | None = None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "KIT_TOOLS":
                    kit_tools_node = node
                    break

    if kit_tools_node is None:
        issues.append(
            Issue(
                "ERROR",
                1,
                "KIT_TOOLS is not defined at module level. Every tool you "
                "want the agent to see must appear in this list.",
            )
        )
        return issues

    if not isinstance(kit_tools_node.value, (ast.List, ast.Tuple)):
        issues.append(
            Issue(
                "ERROR",
                kit_tools_node.lineno,
                "KIT_TOOLS must be a list or tuple literal of decorated tool "
                "function names so this linter can verify it statically.",
            )
        )
        return issues

    listed: list[str] = []
    for elt in kit_tools_node.value.elts:
        if isinstance(elt, ast.Name):
            listed.append(elt.id)
        else:
            issues.append(
                Issue(
                    "WARNING",
                    elt.lineno,
                    "KIT_TOOLS entries should be bare tool function names "
                    "(not calls or attribute access) so the linter can "
                    "verify them.",
                )
            )

    if not listed:
        issues.append(
            Issue(
                "ERROR",
                kit_tools_node.lineno,
                "KIT_TOOLS is empty. Add the tool functions you want the "
                "agent to use.",
            )
        )

    for name in listed:
        if name not in decorated_names:
            issues.append(
                Issue(
                    "ERROR",
                    kit_tools_node.lineno,
                    f"KIT_TOOLS references '{name}', which is not a function "
                    "decorated with @beta_async_tool in this module.",
                )
            )

    for name in sorted(decorated_names - set(listed)):
        issues.append(
            Issue(
                "WARNING",
                1,
                f"tool '{name}' is decorated with @beta_async_tool but is "
                "not in KIT_TOOLS, so the agent will not see it.",
            )
        )

    return issues


def check_file(path: Path) -> list[Issue]:
    """Run all rules against ``path``. Returns the list of issues (possibly empty)."""
    if not path.exists():
        return [Issue("ERROR", 1, f"file not found: {path}")]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        return [Issue("ERROR", e.lineno or 1, f"syntax error: {e.msg}")]

    issues: list[Issue] = []
    decorated_names: set[str] = set()

    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        names = {_decorator_name(d) for d in node.decorator_list}
        if not (names & TOOL_DECORATORS):
            continue
        decorated_names.add(node.name)
        issues.extend(_check_tool_func(node))

    issues.extend(_check_kit_tools(tree, decorated_names))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-flight linter for kit tool modules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Tool modules to check.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exit non-zero on any warning).",
    )
    args = parser.parse_args(argv)

    targets = args.paths or DEFAULT_EXAMPLE_TOOL_MODULES
    exit_code = 0

    for path in targets:
        issues = check_file(path)
        if not issues:
            print(f"{path}: PASS")
            continue
        print(f"{path}:")
        for issue in issues:
            print(f"  {issue.severity} line {issue.line}: {issue.message}")
        if any(i.severity == "ERROR" for i in issues):
            exit_code = 1
        elif args.strict and issues:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
