"""Tests for ``scripts/doctor.py`` primitives.

Exercises ``run_step`` and ``run_steps`` against trivial commands so the
runner's PASS/FAIL/timing logic is verified without spawning the full kit
health check (which would recursively invoke pytest and loop). Step
construction is also covered by ``build_default_steps``.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from doctor import Step, build_default_steps, run_step, run_steps  # noqa: E402


def _passing_step(name: str = "ok") -> Step:
    return Step(name=name, cmd=[sys.executable, "-c", "import sys; sys.exit(0)"])


def _failing_step(name: str = "boom", stderr_msg: str = "deliberate") -> Step:
    return Step(
        name=name,
        cmd=[
            sys.executable,
            "-c",
            f"import sys; print('out'); sys.stderr.write({stderr_msg!r}); sys.exit(1)",
        ],
    )


def test_run_step_passing_command():
    result = run_step(_passing_step())
    assert result.passed is True
    assert result.elapsed >= 0
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)


def test_run_step_failing_command_captures_output():
    result = run_step(_failing_step(stderr_msg="went bad"))
    assert result.passed is False
    assert "out" in result.stdout
    assert "went bad" in result.stderr


def test_run_step_does_not_raise_on_nonzero_exit():
    # Whatever the command's exit code, run_step must return a StepResult,
    # never propagate a CalledProcessError -- the runner aggregates results.
    result = run_step(_failing_step())
    assert result.passed is False


def test_run_steps_all_pass(capsys):
    code = run_steps([_passing_step("first"), _passing_step("second")])
    assert code == 0
    out = capsys.readouterr().out
    assert "[1/2]" in out and "[2/2]" in out
    assert "PASS" in out
    assert "2/2 PASS" in out


def test_run_steps_any_fail_returns_nonzero(capsys):
    code = run_steps([_passing_step("good"), _failing_step("bad")])
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "1/2 PASS, 1 FAIL" in out
    # Failing step dumps its stdout/stderr so the user can fix without re-running.
    assert "out" in out  # the failing step's stdout was dumped


def test_run_steps_continues_past_first_failure(capsys):
    """A failure mid-way through should not abort the rest of the run --
    the user wants the full picture in one pass, not a fix-and-rerun loop."""
    code = run_steps(
        [_passing_step("a"), _failing_step("b"), _passing_step("c")]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "[3/3]" in out  # third step did execute
    assert "2/3 PASS, 1 FAIL" in out


def test_build_default_steps_has_expected_shape():
    """The canonical step list covers ruff, pytest, check_tools, every example
    verify, and the two-step scaffold drift check."""
    steps = build_default_steps(fix=False)
    names = [s.name for s in steps]
    assert any("ruff" in n for n in names)
    assert any("pytest" in n for n in names)
    assert any("check_tools" in n for n in names)
    # One verify step per example kit currently in the repo.
    verify_names = [n for n in names if n.endswith("verify")]
    assert len(verify_names) >= 4  # data, api, db, queue (more as we add)
    # Scaffold drift check is two steps.
    assert any(n.startswith("scaffold") for n in names)
    assert "verify scaffolded kit" in names


def test_build_default_steps_fix_flag_adds_ruff_flag():
    steps_no_fix = build_default_steps(fix=False)
    steps_fix = build_default_steps(fix=True)
    ruff_no_fix = next(s for s in steps_no_fix if "ruff" in s.name)
    ruff_fix = next(s for s in steps_fix if "ruff" in s.name)
    assert "--fix" not in ruff_no_fix.cmd
    assert "--fix" in ruff_fix.cmd
    assert "--fix" in ruff_fix.name
