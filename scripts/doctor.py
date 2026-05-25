"""One-command local health check for the kit.

Runs the same checks CI runs, in order, with per-step PASS/FAIL output and a
final tally. Use this before pushing so red CI is a surprise, not a habit.

Steps (8):
  1. ruff check .                 (or `--fix` if `--fix` is passed)
  2. pytest -q                    full offline test suite
  3. check_tools.py --strict      pre-flight lint over all example tool modules
  4-7. each example's verify.py   factory + tool surface + offline I/O
  8. scaffold + verify a fresh kit (the CI drift check, locally)

Exit 0 if all pass, 1 if any fail. Stdout/stderr of failing steps is dumped
in full so the failure is fixable without re-running the underlying command.

Usage:
    python scripts/doctor.py            # check only
    python scripts/doctor.py --fix      # auto-apply ruff fixes on step 1
    python scripts/doctor.py -v         # also dump stdout/stderr of PASSING steps
"""
from __future__ import annotations

import argparse
import atexit
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


@dataclass(frozen=True)
class Step:
    name: str
    cmd: list[str]
    cwd: Path = REPO_ROOT


@dataclass(frozen=True)
class StepResult:
    step: Step
    passed: bool
    elapsed: float
    stdout: str
    stderr: str


def run_step(step: Step) -> StepResult:
    """Run a single step. Always returns a result; never raises."""
    t0 = time.monotonic()
    proc = subprocess.run(
        step.cmd, cwd=step.cwd, capture_output=True, text=True, check=False
    )
    return StepResult(
        step=step,
        passed=proc.returncode == 0,
        elapsed=time.monotonic() - t0,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _format_line(idx: int, total: int, name: str, status: str, elapsed: float) -> str:
    # Pad name to a consistent width for readable columns; cap at 40 chars.
    padded = name[:40].ljust(40, ".")
    return f"[{idx}/{total}] {padded} {status} ({elapsed:.1f}s)"


def run_steps(steps: list[Step], verbose: bool = False) -> int:
    """Run steps in order, print per-step status, return overall exit code."""
    results: list[StepResult] = []
    total = len(steps)
    overall_start = time.monotonic()

    for i, step in enumerate(steps, start=1):
        result = run_step(step)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(_format_line(i, total, step.name, status, result.elapsed), flush=True)
        if verbose and result.passed and (result.stdout or result.stderr):
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
        if not result.passed:
            print(f"--- {step.name} stdout ---")
            print(result.stdout or "(empty)")
            print(f"--- {step.name} stderr ---")
            print(result.stderr or "(empty)")

    passed_count = sum(1 for r in results if r.passed)
    overall_elapsed = time.monotonic() - overall_start
    summary = f"{passed_count}/{total} PASS"
    if passed_count != total:
        summary += f", {total - passed_count} FAIL"
    print(f"\n{summary} in {overall_elapsed:.1f}s")

    return 0 if passed_count == total else 1


def _scaffold_drift_steps() -> list[Step]:
    """Two-step scaffold-drift check (matches the CI step).

    Step 1 scaffolds a fresh kit into a tmp dir; step 2 runs that kit's
    verify.py. Keeping them as separate Steps means a failure points at
    the right phase (scaffold vs. verify) and the runner's PASS/FAIL line
    stays atomic per phase.
    """
    tmp = Path(tempfile.mkdtemp(prefix="doctor_scaffold_"))
    # Clean up the scratch dir on process exit so repeated doctor runs don't
    # accumulate doctor_scaffold_* dirs in TMPDIR. ignore_errors so a partial
    # run that left an unreadable file does not crash exit.
    atexit.register(shutil.rmtree, tmp, True)
    name = "doctor_scaffold_smoke"
    scaffolded = tmp / name
    return [
        Step(
            name="scaffold a fresh kit (db pattern)",
            cmd=[
                sys.executable,
                str(REPO_ROOT / "scripts" / "new_example.py"),
                name,
                "--pattern",
                "db",
                "--dest",
                str(tmp),
            ],
        ),
        Step(
            name="verify scaffolded kit",
            cmd=[sys.executable, "verify.py"],
            cwd=scaffolded,
        ),
    ]


def _example_verify_steps() -> list[Step]:
    return [
        Step(
            name=f"{p.parent.name} verify",
            cmd=[sys.executable, "verify.py"],
            cwd=p.parent,
        )
        for p in sorted(EXAMPLES.glob("internal_*_kit/verify.py"))
    ]


def build_default_steps(*, fix: bool) -> list[Step]:
    """The canonical step list `python scripts/doctor.py` runs."""
    ruff_cmd = [sys.executable, "-m", "ruff", "check", "."]
    if fix:
        ruff_cmd.append("--fix")
    steps: list[Step] = [
        Step("ruff check" + (" --fix" if fix else ""), ruff_cmd),
        Step("pytest", [sys.executable, "-m", "pytest", "-q"]),
        Step(
            "check_tools.py --strict",
            [sys.executable, "scripts/check_tools.py", "--strict"],
        ),
    ]
    steps.extend(_example_verify_steps())
    steps.extend(_scaffold_drift_steps())
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-command local health check for the kit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Pass --fix to ruff so auto-fixable lint issues are corrected in place.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Also dump stdout/stderr of PASSING steps (failing steps always dump).",
    )
    args = parser.parse_args(argv)

    if shutil.which("git") is None:
        # Not strictly required, but a useful early sanity check.
        print("warning: git not found on PATH (doctor.py does not need it; pytest might)")

    steps = build_default_steps(fix=args.fix)
    return run_steps(steps, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
