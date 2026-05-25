"""Tests for ``scripts/validate.py``.

validate.py is the pre-flight check an adopter runs before `modal deploy`,
so its failure messages need to be accurate and its checks need to fire
under the right conditions. Each check function is exercised here by
monkeypatching either ``subprocess.run`` (for the Modal CLI checks) or
``importlib.import_module`` / ``os.environ`` (for the SDK + env checks).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate  # noqa: E402


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# --------------------------------------------------------------------------- #
# check_anthropic_sdk
# --------------------------------------------------------------------------- #
def test_check_anthropic_sdk_pass(capsys):
    """The real installed SDK should be detected and pass the version gate."""
    assert validate.check_anthropic_sdk() is True
    out = capsys.readouterr().out
    assert "OK" in out
    assert "anthropic " in out


def test_check_anthropic_sdk_missing(monkeypatch, capsys):
    def _raise_import(_name):
        raise ImportError("no such module")

    monkeypatch.setattr(validate.importlib, "import_module", _raise_import)
    assert validate.check_anthropic_sdk() is False
    err = capsys.readouterr().err
    assert "anthropic is not installed" in err


def test_check_anthropic_sdk_too_old(monkeypatch, capsys):
    fake = SimpleNamespace(__version__="0.102.0", AsyncAnthropic=object)
    monkeypatch.setattr(validate.importlib, "import_module", lambda _name: fake)
    assert validate.check_anthropic_sdk() is False
    err = capsys.readouterr().err
    assert "older than required" in err
    assert "0.102.0" in err


def test_check_anthropic_sdk_missing_AsyncAnthropic(monkeypatch, capsys):
    """An installed package that does not expose AsyncAnthropic is a broken install."""
    fake = SimpleNamespace(__version__="0.103.1")
    monkeypatch.setattr(validate.importlib, "import_module", lambda _name: fake)
    assert validate.check_anthropic_sdk() is False
    err = capsys.readouterr().err
    assert "AsyncAnthropic is missing" in err


# --------------------------------------------------------------------------- #
# check_modal_auth
# --------------------------------------------------------------------------- #
def test_check_modal_auth_pass(monkeypatch, capsys):
    monkeypatch.setattr(
        validate.subprocess,
        "run",
        lambda *a, **k: _completed(stdout="my-workspace\n", returncode=0),
    )
    assert validate.check_modal_auth() is True
    out = capsys.readouterr().out
    assert "OK" in out
    assert "my-workspace" in out


def test_check_modal_auth_not_authed(monkeypatch, capsys):
    monkeypatch.setattr(
        validate.subprocess,
        "run",
        lambda *a, **k: _completed(returncode=1, stderr="not authed"),
    )
    assert validate.check_modal_auth() is False
    err = capsys.readouterr().err
    assert "modal setup" in err


def test_check_modal_auth_cli_missing(monkeypatch, capsys):
    def _raise(*a, **k):
        raise FileNotFoundError("modal not on PATH")

    monkeypatch.setattr(validate.subprocess, "run", _raise)
    assert validate.check_modal_auth() is False
    err = capsys.readouterr().err
    assert "modal CLI not found" in err


def test_check_modal_auth_timeout(monkeypatch, capsys):
    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="modal", timeout=10)

    monkeypatch.setattr(validate.subprocess, "run", _raise)
    assert validate.check_modal_auth() is False
    err = capsys.readouterr().err
    assert "timed out" in err


# --------------------------------------------------------------------------- #
# check_modal_secret
# --------------------------------------------------------------------------- #
def test_check_modal_secret_present(monkeypatch, capsys):
    secrets = [{"Name": validate.SECRET_NAME}, {"Name": "other-secret"}]
    monkeypatch.setattr(
        validate.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps(secrets), returncode=0),
    )
    assert validate.check_modal_secret() is True
    out = capsys.readouterr().out
    assert validate.SECRET_NAME in out


def test_check_modal_secret_absent(monkeypatch, capsys):
    """The expected secret name is not in the list -- fail with the create hint."""
    secrets = [{"Name": "some-other-secret"}]
    monkeypatch.setattr(
        validate.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps(secrets), returncode=0),
    )
    assert validate.check_modal_secret() is False
    err = capsys.readouterr().err
    assert "does not exist" in err
    assert "README step 3" in err


def test_check_modal_secret_command_failed(monkeypatch, capsys):
    monkeypatch.setattr(
        validate.subprocess,
        "run",
        lambda *a, **k: _completed(returncode=1, stderr="auth required"),
    )
    assert validate.check_modal_secret() is False
    err = capsys.readouterr().err
    assert "modal secret list failed" in err


def test_check_modal_secret_unparseable_json(monkeypatch, capsys):
    monkeypatch.setattr(
        validate.subprocess,
        "run",
        lambda *a, **k: _completed(stdout="not json{", returncode=0),
    )
    assert validate.check_modal_secret() is False
    err = capsys.readouterr().err
    assert "could not parse" in err


# --------------------------------------------------------------------------- #
# check_env_key_shape
# --------------------------------------------------------------------------- #
def test_check_env_key_shape_not_set_is_non_fatal(monkeypatch, capsys):
    """The live key is in the Modal Secret, not local env. Absence is OK."""
    monkeypatch.delenv("ANTHROPIC_ENVIRONMENT_KEY", raising=False)
    assert validate.check_env_key_shape() is True
    out = capsys.readouterr().out
    assert "skip shape check" in out


def test_check_env_key_shape_correct_prefix(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_KEY", "sk-ant-oat-abc123")
    assert validate.check_env_key_shape() is True
    out = capsys.readouterr().out
    assert "expected sk-ant-oat- prefix" in out


def test_check_env_key_shape_wrong_prefix_fails(monkeypatch, capsys):
    """A common slip is pasting the org API key where the environment key belongs."""
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_KEY", "sk-ant-api-abc123")
    assert validate.check_env_key_shape() is False
    err = capsys.readouterr().err
    assert "does not start with 'sk-ant-oat-'" in err
    assert "NOT org API keys" in err


# --------------------------------------------------------------------------- #
# main() aggregation
# --------------------------------------------------------------------------- #
def test_main_returns_zero_when_all_checks_pass(monkeypatch, capsys):
    monkeypatch.setattr(validate, "check_anthropic_sdk", lambda: True)
    monkeypatch.setattr(validate, "check_modal_auth", lambda: True)
    monkeypatch.setattr(validate, "check_modal_secret", lambda: True)
    monkeypatch.setattr(validate, "check_env_key_shape", lambda: True)
    assert validate.main() == 0
    out = capsys.readouterr().out
    assert "All checks passed" in out


def test_main_returns_nonzero_when_any_check_fails(monkeypatch, capsys):
    monkeypatch.setattr(validate, "check_anthropic_sdk", lambda: True)
    monkeypatch.setattr(validate, "check_modal_auth", lambda: False)
    monkeypatch.setattr(validate, "check_modal_secret", lambda: True)
    monkeypatch.setattr(validate, "check_env_key_shape", lambda: True)
    assert validate.main() == 1
    err = capsys.readouterr().err
    assert "1 check(s) failed" in err
