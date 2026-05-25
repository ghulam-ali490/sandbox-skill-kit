"""Tests for ``scripts/check_tools.py``.

Synthesises tiny tool modules in tmp_path and asserts each rule fires
exactly when it should. Keeps the file standalone (no shared fixtures with
the example tests) so the rules can be read top-to-bottom.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_tools import check_file, main  # noqa: E402


def _write(tmp_path: Path, body: str) -> Path:
    """Drop ``body`` into ``tmp_path/_tools.py`` and return the path."""
    path = tmp_path / "_tools.py"
    path.write_text(body, encoding="utf-8")
    return path


def _severities(issues, *needles):
    """Return the severities of issues whose message contains every needle."""
    return [
        i.severity
        for i in issues
        if all(n in i.message for n in needles)
    ]


CLEAN = '''
from anthropic.lib.tools import beta_async_tool


@beta_async_tool
async def lookup(order_id: str) -> str:
    """Look up an order.

    Args:
        order_id: The order id.
    """
    return f"order {order_id}"


KIT_TOOLS = [lookup]
'''


def test_clean_module_has_no_issues(tmp_path):
    issues = check_file(_write(tmp_path, CLEAN))
    assert issues == []


def test_collision_with_default_toolset(tmp_path):
    body = CLEAN.replace("async def lookup(", "async def read(").replace(
        "KIT_TOOLS = [lookup]", "KIT_TOOLS = [read]"
    )
    issues = check_file(_write(tmp_path, body))
    assert "ERROR" in _severities(issues, "collides with the default toolset")


def test_sync_function_decorated(tmp_path):
    body = CLEAN.replace("async def lookup", "def lookup")
    issues = check_file(_write(tmp_path, body))
    assert "ERROR" in _severities(issues, "must be 'async def'")


def test_missing_param_type_annotation(tmp_path):
    body = CLEAN.replace("order_id: str", "order_id")
    issues = check_file(_write(tmp_path, body))
    assert "ERROR" in _severities(
        issues, "parameter 'order_id'", "missing a type annotation"
    )


def test_missing_docstring(tmp_path):
    body = CLEAN.replace(
        '"""Look up an order.\n\n    Args:\n        order_id: The order id.\n    """',
        "",
    )
    issues = check_file(_write(tmp_path, body))
    # has_params -> missing docstring is an ERROR, not a WARNING
    assert "ERROR" in _severities(issues, "has no docstring")


def test_missing_args_section_is_warning(tmp_path):
    body = CLEAN.replace(
        '"""Look up an order.\n\n    Args:\n        order_id: The order id.\n    """',
        '"""Look up an order."""',
    )
    issues = check_file(_write(tmp_path, body))
    # has_params + has docstring + no Args: -> WARNING
    assert _severities(issues, "no 'Args:' section") == ["WARNING"]


def test_missing_kit_tools(tmp_path):
    body = CLEAN.replace("KIT_TOOLS = [lookup]", "")
    issues = check_file(_write(tmp_path, body))
    assert "ERROR" in _severities(issues, "KIT_TOOLS is not defined")


def test_empty_kit_tools(tmp_path):
    body = CLEAN.replace("KIT_TOOLS = [lookup]", "KIT_TOOLS = []")
    issues = check_file(_write(tmp_path, body))
    assert "ERROR" in _severities(issues, "KIT_TOOLS is empty")


def test_kit_tools_references_unknown_name(tmp_path):
    body = CLEAN.replace("KIT_TOOLS = [lookup]", "KIT_TOOLS = [does_not_exist]")
    issues = check_file(_write(tmp_path, body))
    assert "ERROR" in _severities(issues, "references 'does_not_exist'")


def test_orphan_decorated_tool_is_warning(tmp_path):
    # Two tools defined, KIT_TOOLS only lists one -> WARNING for the orphan.
    body = CLEAN.replace(
        "KIT_TOOLS = [lookup]",
        '''
@beta_async_tool
async def orphan(x: str) -> str:
    """Orphan.

    Args:
        x: A value.
    """
    return x


KIT_TOOLS = [lookup]
''',
    )
    issues = check_file(_write(tmp_path, body))
    assert "WARNING" in _severities(issues, "tool 'orphan'", "not in KIT_TOOLS")


def test_kit_tools_must_be_list_or_tuple(tmp_path):
    body = CLEAN.replace("KIT_TOOLS = [lookup]", "KIT_TOOLS = lookup")
    issues = check_file(_write(tmp_path, body))
    assert "ERROR" in _severities(issues, "must be a list or tuple")


def test_syntax_error_is_reported(tmp_path):
    issues = check_file(_write(tmp_path, "def broken("))
    assert any(i.severity == "ERROR" and "syntax error" in i.message for i in issues)


def test_missing_file(tmp_path):
    issues = check_file(tmp_path / "nope.py")
    assert any(
        i.severity == "ERROR" and "file not found" in i.message for i in issues
    )


def test_main_exit_clean(tmp_path, capsys):
    path = _write(tmp_path, CLEAN)
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out


def test_main_exit_nonzero_on_error(tmp_path):
    path = _write(tmp_path, CLEAN.replace("KIT_TOOLS = [lookup]", ""))
    assert main([str(path)]) == 1


def test_strict_promotes_warning_to_failure(tmp_path):
    # Orphan tool produces a WARNING; --strict should make it fail.
    body = CLEAN.replace(
        "KIT_TOOLS = [lookup]",
        '''
@beta_async_tool
async def orphan(x: str) -> str:
    """Orphan.

    Args:
        x: A value.
    """
    return x


KIT_TOOLS = [lookup]
''',
    )
    path = _write(tmp_path, body)
    assert main([str(path)]) == 0  # not strict -> warnings don't fail
    assert main([str(path), "--strict"]) == 1


# --------------------------------------------------------------------------- #
# Decorator alias detection (closes the v0.1 known limitation)
# --------------------------------------------------------------------------- #
ALIASED = '''
from anthropic.lib.tools import beta_async_tool as tool


@tool
async def lookup(order_id: str) -> str:
    """Look up an order.

    Args:
        order_id: The order id.
    """
    return f"order {order_id}"


KIT_TOOLS = [lookup]
'''


def test_aliased_decorator_import_is_detected(tmp_path):
    """Closes the v0.1 limitation: `from ... import beta_async_tool as tool`
    used as `@tool` should be recognised exactly like the bare name."""
    issues = check_file(_write(tmp_path, ALIASED))
    assert issues == []
    # Sanity check: KIT_TOOLS = [lookup] is satisfied, meaning the linter
    # treated `lookup` as a decorated tool (otherwise KIT_TOOLS would have
    # complained about referencing an undecorated name).


def test_aliased_decorator_rules_still_fire(tmp_path):
    """Make sure the alias path doesn't bypass the normal rules."""
    bad = ALIASED.replace("async def lookup(order_id: str)", "async def read(order_id: str)")
    bad = bad.replace("KIT_TOOLS = [lookup]", "KIT_TOOLS = [read]")
    issues = check_file(_write(tmp_path, bad))
    assert "ERROR" in _severities(issues, "collides with the default toolset")


def test_aliased_decorator_with_short_alias(tmp_path):
    body = ALIASED.replace(
        "from anthropic.lib.tools import beta_async_tool as tool",
        "from anthropic.lib.tools import beta_async_tool as t",
    ).replace("@tool", "@t")
    issues = check_file(_write(tmp_path, body))
    assert issues == []


def test_multiple_aliases_all_detected(tmp_path):
    """Two aliased imports of beta_async_tool; both should be recognised."""
    body = '''
from anthropic.lib.tools import beta_async_tool as a
from anthropic.lib.tools import beta_async_tool as b


@a
async def first(x: str) -> str:
    """First.

    Args:
        x: A value.
    """
    return x


@b
async def second(y: str) -> str:
    """Second.

    Args:
        y: A value.
    """
    return y


KIT_TOOLS = [first, second]
'''
    issues = check_file(_write(tmp_path, body))
    assert issues == []


def test_unrelated_import_aliased_to_tool_is_ignored(tmp_path):
    """`from somewhere import unrelated as tool` then `@tool` should NOT be
    treated as a kit tool, even though the local name matches a common
    alias pattern."""
    body = '''
from somewhere import unrelated as tool


@tool
async def lookup(order_id: str) -> str:
    """Look up an order.

    Args:
        order_id: The order id.
    """
    return f"order {order_id}"


KIT_TOOLS = []
'''
    issues = check_file(_write(tmp_path, body))
    # Because `lookup` is NOT recognised as a tool, KIT_TOOLS = [] is flagged
    # for being empty -- but no per-tool rule should have fired against `lookup`.
    assert all("tool 'lookup'" not in i.message for i in issues)


@pytest.mark.parametrize(
    "example_path",
    [
        "examples/internal_data_kit/internal_tools.py",
        "examples/internal_api_kit/internal_api_tools.py",
        "examples/internal_db_kit/internal_db_tools.py",
        "examples/internal_queue_kit/internal_queue_tools.py",
    ],
)
def test_real_examples_are_clean(example_path):
    """The three shipped examples must always pass the linter -- they are
    what authors are told to copy."""
    issues = check_file(REPO_ROOT / example_path)
    assert issues == [], f"{example_path} has unexpected lint issues: {issues}"
