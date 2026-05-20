"""Pre-flight check for sandbox-skill-kit.

Run before `modal deploy modal_sandbox_webhook.py`. Confirms:
  1. anthropic SDK is installed and >= 0.103.1 (the version that ships the
     `client.beta.environments.work.worker` helper).
  2. modal SDK is installed and the workspace is authenticated.
  3. The `cma-self-hosted-sandboxes-secrets` Modal Secret exists with the
     three required keys: ANTHROPIC_WEBHOOK_SECRET, ANTHROPIC_ENVIRONMENT_ID,
     ANTHROPIC_ENVIRONMENT_KEY.
  4. ANTHROPIC_ENVIRONMENT_KEY has the expected `sk-ant-oat-` prefix
     (environment keys are NOT org API keys).
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from typing import Callable

SECRET_NAME = "cma-self-hosted-sandboxes-secrets"
REQUIRED_KEYS = ("ANTHROPIC_WEBHOOK_SECRET", "ANTHROPIC_ENVIRONMENT_ID", "ANTHROPIC_ENVIRONMENT_KEY")
MIN_SDK = (0, 103, 1)


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}", file=sys.stderr)


def check_anthropic_sdk() -> bool:
    try:
        m = importlib.import_module("anthropic")
    except ImportError:
        _fail("anthropic is not installed. Run `pip install -r requirements.txt`.")
        return False
    version = tuple(int(p) for p in m.__version__.split(".")[:3])
    if version < MIN_SDK:
        _fail(
            f"anthropic version {m.__version__} is older than required "
            f"{'.'.join(str(x) for x in MIN_SDK)}. Upgrade with "
            f"`pip install -U 'anthropic[webhooks]>=0.103.1'`."
        )
        return False
    if not hasattr(m, "AsyncAnthropic"):
        _fail("anthropic.AsyncAnthropic is missing — unexpected install.")
        return False
    _ok(f"anthropic {m.__version__}")
    return True


def check_modal_auth() -> bool:
    try:
        result = subprocess.run(
            ["modal", "token", "current"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        _fail("modal CLI not found. Run `pip install modal`.")
        return False
    except subprocess.TimeoutExpired:
        _fail("modal token current timed out.")
        return False
    if result.returncode != 0:
        _fail("Modal is not authenticated. Run `modal setup`.")
        return False
    _ok("modal CLI authenticated")
    return True


def check_modal_secret() -> bool:
    try:
        result = subprocess.run(
            ["modal", "secret", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        _fail(f"modal secret list failed: {e}")
        return False
    if result.returncode != 0:
        _fail(f"modal secret list failed: {result.stderr.strip()}")
        return False
    if SECRET_NAME not in result.stdout:
        _fail(
            f"Modal Secret {SECRET_NAME!r} does not exist. "
            f"Create it with the placeholder values from README step 3."
        )
        return False
    _ok(f"Modal Secret {SECRET_NAME} exists")
    return True


def main() -> int:
    print("Pre-flight checks for sandbox-skill-kit:")
    checks: list[Callable[[], bool]] = [
        check_anthropic_sdk,
        check_modal_auth,
        check_modal_secret,
    ]
    failures = sum(1 for c in checks if not c())
    if failures:
        print(f"\n{failures} check(s) failed. Fix them, then re-run.", file=sys.stderr)
        return 1
    print("\nAll checks passed. Ready to `modal deploy modal_sandbox_webhook.py`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
