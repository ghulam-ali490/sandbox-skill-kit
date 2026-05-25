"""Tests for ``scripts/probe_webhook.py``.

The probe script POSTs to a real URL when run live. These tests monkeypatch
the ``_post`` wrapper to return fake responses, so the probe logic + the
signature-building round-trip are verified with no network and no deployed
webhook.

A real `whsec_` shape is needed for the signing tests because
``standardwebhooks.Webhook`` strips and base64-decodes the prefix. We use
a synthetic one + verify the round-trip against the same secret on the
verifier side.
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from probe_webhook import (  # noqa: E402
    PROBE_EVENT_TYPE,
    _build_signed_headers,
    run_probes,
    signed_probe,
    unsigned_probe,
)

# A synthetic whsec_ secret. standardwebhooks strips the "whsec_" prefix and
# base64-decodes the rest, so we just need a valid base64 string after the
# prefix for it to parse.
SYNTHETIC_WHSEC = "whsec_" + base64.b64encode(b"sandbox-skill-kit-test").decode()


def _fake_response(status_code: int, json_body: dict | None = None, text: str = ""):
    """Build a SimpleNamespace that matches httpx.Response's surface."""

    def _json():
        if json_body is None:
            raise json.JSONDecodeError("no body", "", 0)
        return json_body

    resp = SimpleNamespace(
        status_code=status_code,
        text=text or (json.dumps(json_body) if json_body else ""),
        json=_json,
    )
    return resp


# --------------------------------------------------------------------------- #
# unsigned_probe
# --------------------------------------------------------------------------- #
def test_unsigned_probe_passes_on_401(monkeypatch):
    monkeypatch.setattr("probe_webhook._post", lambda *a, **k: _fake_response(401))
    r = unsigned_probe("http://example.test/webhook")
    assert r.passed is True
    assert "401" in r.detail


def test_unsigned_probe_fails_on_200(monkeypatch):
    """200 means the webhook is not enforcing signatures -- a deploy regression."""
    monkeypatch.setattr("probe_webhook._post", lambda *a, **k: _fake_response(200))
    r = unsigned_probe("http://example.test/webhook")
    assert r.passed is False
    assert "expected 401" in r.detail


def test_unsigned_probe_fails_on_500(monkeypatch):
    monkeypatch.setattr("probe_webhook._post", lambda *a, **k: _fake_response(500))
    r = unsigned_probe("http://example.test/webhook")
    assert r.passed is False
    assert "expected 401" in r.detail


def test_unsigned_probe_fails_on_network_error(monkeypatch):
    import httpx

    def _raise(*a, **k):
        raise httpx.ConnectError("dns lookup failed")

    monkeypatch.setattr("probe_webhook._post", _raise)
    r = unsigned_probe("http://no-such.test/webhook")
    assert r.passed is False
    assert "network error" in r.detail
    assert "ConnectError" in r.detail


# --------------------------------------------------------------------------- #
# _build_signed_headers (round-trip against standardwebhooks verifier)
# --------------------------------------------------------------------------- #
def test_signed_headers_round_trip():
    """Headers produced by _build_signed_headers must verify under the same
    secret used to sign them. Catches off-by-one or wrong-field bugs."""
    from standardwebhooks import Webhook

    body = b'{"hello":"world"}'
    msg_id = "msg_test_1"
    ts = datetime.now(tz=UTC)
    headers = _build_signed_headers(SYNTHETIC_WHSEC, body=body, msg_id=msg_id, timestamp=ts)

    assert headers["webhook-id"] == msg_id
    assert headers["webhook-timestamp"] == str(int(ts.timestamp()))
    assert headers["webhook-signature"].startswith("v1,")

    # Round-trip: verify with the same secret. .verify() raises on mismatch.
    Webhook(SYNTHETIC_WHSEC).verify(body.decode(), headers)


# --------------------------------------------------------------------------- #
# signed_probe
# --------------------------------------------------------------------------- #
def test_signed_probe_passes_on_200_ignored(monkeypatch):
    monkeypatch.setattr(
        "probe_webhook._post",
        lambda *a, **k: _fake_response(
            200, {"status": "ignored", "event_type": PROBE_EVENT_TYPE}
        ),
    )
    r = signed_probe("http://example.test/webhook", SYNTHETIC_WHSEC)
    assert r.passed is True
    assert "signature verified" in r.detail


def test_signed_probe_fails_on_401(monkeypatch):
    """401 here means the handler rejected our signature -- secret mismatch."""
    monkeypatch.setattr(
        "probe_webhook._post",
        lambda *a, **k: _fake_response(401, text="signature verification failed"),
    )
    r = signed_probe("http://example.test/webhook", SYNTHETIC_WHSEC)
    assert r.passed is False
    assert "401" in r.detail
    assert "secret mismatch" in r.detail


def test_signed_probe_fails_on_unexpected_status_field(monkeypatch):
    monkeypatch.setattr(
        "probe_webhook._post",
        lambda *a, **k: _fake_response(200, {"status": "ok", "spawned": []}),
    )
    r = signed_probe("http://example.test/webhook", SYNTHETIC_WHSEC)
    assert r.passed is False
    assert "expected status=ignored" in r.detail


def test_signed_probe_fails_on_wrong_event_type_echo(monkeypatch):
    monkeypatch.setattr(
        "probe_webhook._post",
        lambda *a, **k: _fake_response(
            200, {"status": "ignored", "event_type": "something.else"}
        ),
    )
    r = signed_probe("http://example.test/webhook", SYNTHETIC_WHSEC)
    assert r.passed is False
    assert "event_type echoed back" in r.detail


# Note on bad whsec handling: standardwebhooks.Webhook() does not raise on
# malformed secrets at construct time -- it accepts them and produces a bad
# signature that the server then rejects. So the "bad secret" failure mode
# manifests as a 401 from the server (covered by test_signed_probe_fails_on_401),
# not as a sign-time exception. No separate test needed.


# --------------------------------------------------------------------------- #
# run_probes orchestration
# --------------------------------------------------------------------------- #
def test_run_probes_unsigned_only_when_no_secret(monkeypatch, capsys):
    monkeypatch.setattr("probe_webhook._post", lambda *a, **k: _fake_response(401))
    code = run_probes("http://example.test/webhook", whsecret=None)
    out = capsys.readouterr().out
    assert code == 0
    assert "SKIP" in out
    assert "signed probe" in out  # mentioned in the SKIP line
    assert "PASS" in out


def test_run_probes_both_pass(monkeypatch, capsys):
    sequence = [
        _fake_response(401),  # unsigned probe
        _fake_response(200, {"status": "ignored", "event_type": PROBE_EVENT_TYPE}),
    ]

    def _next_response(*a, **k):
        return sequence.pop(0)

    monkeypatch.setattr("probe_webhook._post", _next_response)
    code = run_probes("http://example.test/webhook", whsecret=SYNTHETIC_WHSEC)
    out = capsys.readouterr().out
    assert code == 0
    assert "All probes passed" in out
    # Confirm both probes ran (sequence drained).
    assert sequence == []


def test_run_probes_fail_when_unsigned_returns_200(monkeypatch, capsys):
    monkeypatch.setattr("probe_webhook._post", lambda *a, **k: _fake_response(200))
    code = run_probes("http://example.test/webhook", whsecret=None)
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out
    assert "modal app logs" in out
