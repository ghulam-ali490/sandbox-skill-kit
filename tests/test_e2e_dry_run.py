"""Level 3 dry-run: exercise ``scripts/e2e_test.py`` orchestration against a
stubbed Anthropic client.

The real Level 3 path needs Anthropic Research Preview access (waitlist at
https://claude.com/form/claude-managed-agents). Until that lands, this module
proves the orchestration logic in ``e2e_test.run()`` is correct by running it
against a scripted fake of the Anthropic SDK surface. Closes the v0.1 + v0.2
"Level 3 not exercised end-to-end" known limitation -- we cannot prove a real
CMA session works, but we can prove the kit's driver script will do the right
thing the moment one does.

What the fake covers:
  - ``client.beta.agents.create(...)`` returning an object with ``.id``
  - ``client.beta.sessions.create(...)`` returning ``.id`` + ``.status``
  - ``client.beta.sessions.retrieve(session_id)`` returning ``.status`` from a
    configurable status sequence (one value per call, sticks at last value)
  - ``client.beta.sessions.events.send(session_id, events=...)`` (no-op)
  - ``client.beta.sessions.events.list(session_id, order=...)`` returning a
    configurable transcript

What the fake does NOT cover (out of scope for orchestration logic):
  - Webhook delivery / signature verification (covered by test_webhook_flow.py)
  - The Modal sandbox runner side (real CMA needed)
  - Network errors / retries (CMA-only failure modes)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from e2e_test import run  # noqa: E402


# --------------------------------------------------------------------------- #
# FakeAnthropic: scriptable stand-in for anthropic.Anthropic
# --------------------------------------------------------------------------- #
def _event(event_type: str, **fields) -> SimpleNamespace:
    """Helper: build a fake session event object."""
    return SimpleNamespace(type=event_type, **fields)


class _FakeAgents:
    def __init__(self):
        self.create_calls: list[dict] = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id="agt_fake_001")


class _FakeEvents:
    def __init__(self, parent: FakeAnthropic):
        self.parent = parent
        self.send_calls: list[dict] = []

    def send(self, session_id, *, events):
        self.send_calls.append({"session_id": session_id, "events": events})

    def list(self, session_id, *, order):
        return list(self.parent.transcript)


class _FakeSessions:
    def __init__(self, parent: FakeAnthropic):
        self.parent = parent
        self.events = _FakeEvents(parent)
        self._retrieve_calls = 0
        self._created: list[SimpleNamespace] = []

    def create(self, *, agent, environment_id, title):
        session = SimpleNamespace(
            id="sess_fake_001",
            status=self.parent.status_sequence[0],
        )
        self._created.append(session)
        return session

    def retrieve(self, session_id):
        idx = min(self._retrieve_calls, len(self.parent.status_sequence) - 1)
        self._retrieve_calls += 1
        return SimpleNamespace(
            id=session_id, status=self.parent.status_sequence[idx]
        )


class _FakeBeta:
    def __init__(self, parent: FakeAnthropic):
        self.agents = _FakeAgents()
        self.sessions = _FakeSessions(parent)


class FakeAnthropic:
    """Drop-in fake for ``anthropic.Anthropic`` covering the surface
    ``e2e_test.run`` touches.

    Args:
        status_sequence: One status string per ``sessions.retrieve(...)`` call.
            Once exhausted, the last value sticks. Typical happy-path:
            ``["running", "running", "idle"]``.
        transcript: Events ``sessions.events.list(...)`` will return.
    """

    def __init__(self, *, status_sequence: list[str], transcript: list):
        if not status_sequence:
            raise ValueError("status_sequence must have at least one entry")
        self.status_sequence = list(status_sequence)
        self.transcript = list(transcript)
        self.beta = _FakeBeta(self)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _run(client: FakeAnthropic, *, agent_id: str | None = "agt_pre_set") -> int:
    """Invoke run() with short polling so wall time stays low."""
    return run(
        client,
        agent_id=agent_id,
        environment_id="env_fake_001",
        prompt="test prompt",
        poll_seconds=0.01,
        timeout_seconds=0.5,
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_happy_path_passes(capsys):
    """Status: running -> idle. Transcript has a tool_use + an agent.message
    and no errors. Expected: exit 0, "PASS" printed."""
    client = FakeAnthropic(
        status_sequence=["running", "idle"],
        transcript=[
            _event("user.message", text="run uname"),
            _event("agent.tool_use", name="bash", command="uname -a"),
            _event("agent.tool_result", content="Linux sandbox 6.x"),
            _event("agent.message", text="The sandbox is on Linux 6.x."),
        ],
    )
    code = _run(client)
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out
    assert "agent tool-use events: 1" in out
    assert "error events:          0" in out


def test_terminated_status_also_passes(capsys):
    """The script accepts 'terminated' as a terminal status too."""
    client = FakeAnthropic(
        status_sequence=["running", "terminated"],
        transcript=[
            _event("agent.tool_use", name="bash"),
            _event("agent.message", text="done"),
        ],
    )
    code = _run(client)
    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_auto_creates_agent_when_id_unset(capsys):
    """If agent_id is None, run() asks the client to create one."""
    client = FakeAnthropic(
        status_sequence=["idle"],
        transcript=[_event("agent.tool_use"), _event("agent.message")],
    )
    code = _run(client, agent_id=None)
    out = capsys.readouterr().out
    assert code == 0
    # Confirm the creation actually happened.
    create_calls = client.beta.agents.create_calls
    assert len(create_calls) == 1
    assert create_calls[0]["name"] == "sandbox-skill-kit-e2e"
    assert "created agent agt_fake_001" in out


# --------------------------------------------------------------------------- #
# Failure paths -- each one a real production scenario the script must catch
# --------------------------------------------------------------------------- #
def test_no_tool_use_fails(capsys):
    """Agent went straight to a text reply without invoking any tool. This is
    the signal that the Modal webhook isn't routing tool execution."""
    client = FakeAnthropic(
        status_sequence=["running", "idle"],
        transcript=[
            _event("user.message", text="run uname"),
            _event("agent.message", text="I cannot run shell commands."),
        ],
    )
    code = _run(client)
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out
    assert "no agent tool-use events" in out


def test_error_event_fails(capsys):
    """Any 'error' substring in an event type is a hard fail."""
    client = FakeAnthropic(
        status_sequence=["running", "idle"],
        transcript=[
            _event("agent.tool_use", name="bash"),
            _event("agent.tool_error", error="sandbox unreachable"),
            _event("agent.message", text="error"),
        ],
    )
    code = _run(client)
    out = capsys.readouterr().out
    assert code == 1
    assert "session reported error events" in out


def test_timeout_when_stuck_running(capsys):
    """Status never reaches idle within timeout_seconds -- fail with a
    'check modal app logs' hint."""
    client = FakeAnthropic(
        status_sequence=["running"],  # sticks at running forever
        transcript=[_event("agent.message", text="never runs")],
    )
    code = _run(client)
    out = capsys.readouterr().out
    assert code == 1
    assert "did not reach idle" in out
    assert "webhook may not be firing" in out


def test_session_status_transitions_are_logged(capsys):
    """Each status TRANSITION should produce one [status] line. Running ->
    rescheduling -> running -> idle is three transitions (the second
    'running' is a real transition back from 'rescheduling')."""
    client = FakeAnthropic(
        status_sequence=["running", "rescheduling", "running", "idle"],
        transcript=[_event("agent.tool_use"), _event("agent.message")],
    )
    _run(client)
    out = capsys.readouterr().out
    assert "[status] running" in out
    assert "[status] rescheduling" in out
    assert "[status] idle" in out
    # running -> rescheduling -> running -> idle = 2 'running' transitions + 1
    # 'rescheduling' + 1 'idle' = 4 [status] lines.
    assert out.count("[status]") == 4


def test_repeated_same_status_is_not_re_logged(capsys):
    """While the session stays at 'running', the script should only log it once."""
    client = FakeAnthropic(
        status_sequence=["running", "running", "running", "idle"],
        transcript=[_event("agent.tool_use"), _event("agent.message")],
    )
    _run(client)
    out = capsys.readouterr().out
    assert out.count("[status] running") == 1
    assert out.count("[status] idle") == 1


def test_prompt_is_sent_via_events_send(capsys):
    """The user.message event must include the prompt as a content block."""
    client = FakeAnthropic(
        status_sequence=["idle"],
        transcript=[_event("agent.tool_use"), _event("agent.message")],
    )
    _run(client)
    sent = client.beta.sessions.events.send_calls
    assert len(sent) == 1
    events = sent[0]["events"]
    assert events[0]["type"] == "user.message"
    # Per the SDK API surface, content must be a list of content blocks, not a string.
    content = events[0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "test prompt"
