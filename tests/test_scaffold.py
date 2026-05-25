"""Tests for ``scripts/new_example.py``.

Scaffolds a fresh kit from each of the three templates into a tmp_path, then
asserts the result is structurally correct and the renamed tool module loads
with the expected ``KIT_TOOLS`` surface. This catches drift between the
templates and the scaffold rewriting logic -- e.g. a template adding a new
identifier the scaffold forgets to rename.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from new_example import scaffold  # noqa: E402


def _import_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("pattern", ["data", "api", "db", "queue"])
def test_scaffold_produces_a_runnable_kit(pattern, tmp_path):
    kit = scaffold("acme_billing", pattern, tmp_path)

    # Folder layout.
    assert (kit / "acme_billing_tools.py").exists()
    assert (kit / "sandbox_runner.py").exists()
    assert (kit / "verify.py").exists()
    assert (kit / "README.md").exists()

    # Imports were rewritten -- the new module name must appear, and none of
    # the template's original module names should leak through.
    runner_text = (kit / "sandbox_runner.py").read_text(encoding="utf-8")
    assert "from acme_billing_tools import KIT_TOOLS" in runner_text
    template_modules = (
        "internal_tools",
        "internal_api_tools",
        "internal_db_tools",
        "internal_queue_tools",
    )
    for orig in template_modules:
        if orig != "acme_billing_tools":
            assert orig not in runner_text

    verify_text = (kit / "verify.py").read_text(encoding="utf-8")
    assert "import acme_billing_tools" in verify_text

    # The scaffolded tool module loads and exports the expected surface.
    tools = _import_from_path(
        f"scaffold_test_{pattern}_tools", kit / "acme_billing_tools.py"
    )
    assert hasattr(tools, "KIT_TOOLS")
    assert len(tools.KIT_TOOLS) == 2
    # Tool objects expose the @beta_async_tool surface (name + input_schema).
    for tool in tools.KIT_TOOLS:
        assert getattr(tool, "name", None)
        assert getattr(tool, "input_schema", None)


def test_scaffold_refuses_to_overwrite_existing_dir(tmp_path):
    scaffold("acme_billing", "data", tmp_path)
    with pytest.raises(SystemExit, match="already exists"):
        scaffold("acme_billing", "data", tmp_path)


def test_scaffold_rejects_bad_kit_name(tmp_path):
    with pytest.raises(SystemExit, match="Invalid kit name"):
        scaffold("Bad-Name", "data", tmp_path)


def test_scaffold_rejects_unknown_pattern(tmp_path):
    with pytest.raises(SystemExit, match="Unknown pattern"):
        scaffold("acme_billing", "definitely_not_a_pattern", tmp_path)
