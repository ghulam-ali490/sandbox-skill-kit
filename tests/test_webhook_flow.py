"""Offline tests for the webhook wiring in ``modal_sandbox_webhook.py``.

These mock the Anthropic SDK and Modal entirely, so the core logic
(signature verification, queue drain, get-or-create sandbox, event routing)
is exercised with NO CMA account and NO Modal deploy. This is what proves the
wiring before the CMA-gated Level 3 end-to-end run is available.

What is and is NOT covered:
  - Covered: _verify_webhook, _process_work_item, _drain_work, the webhook
    endpoint's event routing -- i.e. every branch the kit owns.
  - Not covered: the real Modal Sandbox API calls inside _create_sandbox /
    _find_live_sandbox, and the real worker().handle_item() inside the
    sandbox. Those need live Modal + CMA and are covered by scripts/e2e_test.py.
"""

import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import modal_sandbox_webhook as m


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _work(work_id: str, data_type: str, session_id: str):
    """A stand-in for an SDK work item: ``.id`` and ``.data.{type,id}``."""
    return types.SimpleNamespace(
        id=work_id, data=types.SimpleNamespace(type=data_type, id=session_id)
    )


def _client_yielding(works):
    """A fake Anthropic client whose work poller yields ``works`` then stops."""

    async def _gen():
        for w in works:
            yield w

    client = MagicMock()
    client.beta.environments.work.poller = MagicMock(return_value=_gen())
    return client


class _FakeRequest:
    """Minimal stand-in for a FastAPI/Starlette Request."""

    def __init__(self, body: bytes = b"{}", headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


# --------------------------------------------------------------------------- #
# _verify_webhook
# --------------------------------------------------------------------------- #
def test_verify_webhook_returns_event_on_valid_signature():
    event = object()
    client = MagicMock()
    client.beta.webhooks.unwrap.return_value = event

    assert m._verify_webhook(client, b'{"x":1}', {"sig": "v"}) is event
    client.beta.webhooks.unwrap.assert_called_once()


def test_verify_webhook_bad_signature_raises_401():
    from standardwebhooks import WebhookVerificationError

    client = MagicMock()
    client.beta.webhooks.unwrap.side_effect = WebhookVerificationError("bad sig")

    with pytest.raises(HTTPException) as exc:
        m._verify_webhook(client, b"{}", {})
    assert exc.value.status_code == 401


def test_verify_webhook_missing_header_raises_401():
    client = MagicMock()
    client.beta.webhooks.unwrap.side_effect = KeyError("webhook-signature")

    with pytest.raises(HTTPException) as exc:
        m._verify_webhook(client, b"{}", {})
    assert exc.value.status_code == 401


def test_verify_webhook_unexpected_error_propagates():
    # A non-signature error is a bug, not a bad delivery -- it must NOT be
    # masked as a 401.
    client = MagicMock()
    client.beta.webhooks.unwrap.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        m._verify_webhook(client, b"{}", {})


def test_verify_webhook_non_utf8_body_raises_401():
    # Adversarial non-UTF-8 input must reject as 401 (same shape of badness
    # as a bad signature), not propagate the UnicodeDecodeError as a 500
    # (which would leak "the server crashed handling this"). The MagicMock
    # client never gets called because the decode fails first.
    client = MagicMock()
    invalid_utf8 = b"\xff\xfe\xfd not utf-8"

    with pytest.raises(HTTPException) as exc:
        m._verify_webhook(client, invalid_utf8, {})
    assert exc.value.status_code == 401
    # Confirm unwrap was never reached -- the decode short-circuited.
    client.beta.webhooks.unwrap.assert_not_called()


# --------------------------------------------------------------------------- #
# _process_work_item  (get-or-create)
# --------------------------------------------------------------------------- #
async def test_process_work_item_reuses_live_sandbox(monkeypatch):
    existing = types.SimpleNamespace(object_id="sb-existing")
    monkeypatch.setattr(m, "_find_live_sandbox", AsyncMock(return_value=existing))
    create = AsyncMock()
    monkeypatch.setattr(m, "_create_sandbox", create)

    out = await m._process_work_item(
        session_id="s1", work_id="w1", environment_id="env", environment_key="k"
    )

    assert out == {
        "session_id": "s1",
        "work_id": "w1",
        "sandbox_id": "sb-existing",
        "created": False,
    }
    create.assert_not_called()


async def test_process_work_item_creates_when_none_live(monkeypatch):
    monkeypatch.setattr(m, "_find_live_sandbox", AsyncMock(return_value=None))
    new_sb = types.SimpleNamespace(object_id="sb-new")
    monkeypatch.setattr(m, "_create_sandbox", AsyncMock(return_value=new_sb))

    out = await m._process_work_item(
        session_id="s2", work_id="w2", environment_id="env", environment_key="k"
    )

    assert out == {
        "session_id": "s2",
        "work_id": "w2",
        "sandbox_id": "sb-new",
        "created": True,
    }


# --------------------------------------------------------------------------- #
# _drain_work
# --------------------------------------------------------------------------- #
async def test_drain_skips_non_session_work(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_KEY", "sk-ant-oat-test")
    client = _client_yielding([_work("w1", "not-a-session", "s1")])
    process = AsyncMock()
    monkeypatch.setattr(m, "_process_work_item", process)

    out = await m._drain_work(client, "env_test")

    # Skipped items are now returned (with skipped=True) so the caller has
    # visibility into how many work items were ignored. _process_work_item
    # must still not be called for non-session work.
    assert out == [{"work_id": "w1", "type": "not-a-session", "skipped": True}]
    process.assert_not_called()


async def test_drain_spawns_one_sandbox_per_session(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_KEY", "sk-ant-oat-test")
    client = _client_yielding(
        [_work("w1", "session", "s1"), _work("w2", "session", "s2")]
    )

    async def fake_process(*, session_id, work_id, environment_id, environment_key):
        assert environment_key == "sk-ant-oat-test"
        return {"session_id": session_id, "work_id": work_id, "created": True}

    monkeypatch.setattr(m, "_process_work_item", fake_process)

    out = await m._drain_work(client, "env_test")

    assert {r["session_id"] for r in out} == {"s1", "s2"}
    assert all(r["created"] for r in out)


async def test_drain_continues_after_one_spawn_fails(monkeypatch):
    # The poller has already ack'd each item; a spawn failure must be logged
    # and skipped, and the drain must keep going to the next item.
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_KEY", "sk-ant-oat-test")
    client = _client_yielding(
        [_work("w1", "session", "s1"), _work("w2", "session", "s2")]
    )

    async def fake_process(*, session_id, work_id, **_):
        if session_id == "s1":
            raise RuntimeError("modal unreachable")
        return {"session_id": session_id, "work_id": work_id, "created": True}

    monkeypatch.setattr(m, "_process_work_item", fake_process)

    out = await m._drain_work(client, "env_test")

    by_session = {r["session_id"]: r for r in out}
    assert by_session["s1"]["error"] == "RuntimeError"  # logged failure
    assert by_session["s2"]["created"] is True  # later item still spawned


# --------------------------------------------------------------------------- #
# webhook endpoint event routing  (run via Modal Function .local())
# --------------------------------------------------------------------------- #
async def test_webhook_ignores_non_run_started_events(monkeypatch):
    event = types.SimpleNamespace(
        data=types.SimpleNamespace(type="session.status_idle", id="s1")
    )
    monkeypatch.setattr(m, "_client", lambda: MagicMock())
    monkeypatch.setattr(m, "_verify_webhook", lambda *a, **k: event)
    drain = AsyncMock()
    monkeypatch.setattr(m, "_drain_work", drain)

    out = await m.webhook.local(_FakeRequest())

    assert out["status"] == "ignored"
    assert out["event_type"] == "session.status_idle"
    drain.assert_not_called()


async def test_webhook_drains_on_run_started(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_ENVIRONMENT_ID", "env_test")
    event = types.SimpleNamespace(
        data=types.SimpleNamespace(type="session.status_run_started", id="s1")
    )
    monkeypatch.setattr(m, "_client", lambda: MagicMock())
    monkeypatch.setattr(m, "_verify_webhook", lambda *a, **k: event)
    drain = AsyncMock(return_value=[{"session_id": "s1", "created": True}])
    monkeypatch.setattr(m, "_drain_work", drain)

    out = await m.webhook.local(_FakeRequest())

    assert out["status"] == "ok"
    assert out["spawned"] == [{"session_id": "s1", "created": True}]
    drain.assert_awaited_once()


# --------------------------------------------------------------------------- #
# _sandbox_timeout  (env-var configurable lifetime cap)
# --------------------------------------------------------------------------- #
def test_sandbox_timeout_default_when_env_unset(monkeypatch):
    monkeypatch.delenv(m.SANDBOX_TIMEOUT_ENV, raising=False)
    assert m._sandbox_timeout() == m.DEFAULT_SANDBOX_TIMEOUT_SECONDS == 3600


def test_sandbox_timeout_reads_positive_int_from_env(monkeypatch):
    monkeypatch.setenv(m.SANDBOX_TIMEOUT_ENV, "14400")
    assert m._sandbox_timeout() == 14400


@pytest.mark.parametrize("bad", ["not-a-number", "1h", "3600.5", ""])
def test_sandbox_timeout_rejects_non_integer(monkeypatch, bad):
    # A typo in the Modal Secret must fail loudly at first use, not silently
    # misconfigure -- otherwise int("3600.5") would explode at sandbox-create
    # time with a much less actionable error.
    monkeypatch.setenv(m.SANDBOX_TIMEOUT_ENV, bad)
    with pytest.raises(RuntimeError) as exc:
        m._sandbox_timeout()
    assert m.SANDBOX_TIMEOUT_ENV in str(exc.value)


@pytest.mark.parametrize("bad", ["0", "-1", "-3600"])
def test_sandbox_timeout_rejects_non_positive(monkeypatch, bad):
    # Zero-second sandboxes would just churn on create/teardown -- treat
    # 0 and negative as configuration errors, not features.
    monkeypatch.setenv(m.SANDBOX_TIMEOUT_ENV, bad)
    with pytest.raises(RuntimeError) as exc:
        m._sandbox_timeout()
    assert "positive integer" in str(exc.value)


async def test_process_work_item_threads_configured_timeout(monkeypatch):
    # Confirm the env-var value reaches _create_sandbox (the only place that
    # actually uses it), so a misconfigured timeout can't get swallowed by a
    # default elsewhere.
    monkeypatch.delenv(m.SANDBOX_TIMEOUT_ENV, raising=False)
    monkeypatch.setenv(m.SANDBOX_TIMEOUT_ENV, "7200")
    monkeypatch.setattr(m, "_find_live_sandbox", AsyncMock(return_value=None))
    create = AsyncMock(return_value=types.SimpleNamespace(object_id="sb-new"))
    monkeypatch.setattr(m, "_create_sandbox", create)

    await m._process_work_item(
        session_id="s3", work_id="w3", environment_id="env", environment_key="k"
    )

    assert create.await_args.kwargs["sandbox_timeout"] == 7200
