"""End-to-end test for sandbox-skill-kit (Level 3).

Fires a REAL Claude Managed Agents session against your deployed Modal webhook
and confirms that agent tool calls (bash/read/write/...) actually executed
inside your self-hosted Modal Sandbox.

Prerequisites (all must be true before this will work):
  1. `python scripts/validate.py` passes (Modal authed, secret exists, SDK ok).
  2. The Modal Secret holds REAL values, not the Level-2 placeholders:
       ANTHROPIC_ENVIRONMENT_ID   env_...
       ANTHROPIC_ENVIRONMENT_KEY  sk-ant-oat-...
       ANTHROPIC_WEBHOOK_SECRET   whsec_...   (from the Console after you
                                               registered the *.modal.run URL
                                               for session.status_run_started)
  3. The webhook URL is registered in the Anthropic Console for the
     `session.status_run_started` event.

This script talks to the Anthropic control plane only. It needs three env vars
(export them in your shell; never commit them):

  ANTHROPIC_API_KEY         your org key (sk-ant-api...) -- drives session setup
  ANTHROPIC_ENVIRONMENT_ID  the SAME env_... that is in the Modal Secret
  CMA_AGENT_ID              an agent in that environment (agt_...)

If CMA_AGENT_ID is unset, the script offers to create a minimal bash-capable
agent for you and prints its id so you can reuse it.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-api...
    export ANTHROPIC_ENVIRONMENT_ID=env_...
    export CMA_AGENT_ID=agt_...            # optional; omit to auto-create
    python scripts/e2e_test.py

Then, in another terminal, watch the sandbox side:
    modal app logs cma-self-hosted-sandboxes
"""
from __future__ import annotations

import os
import sys
import time

import anthropic

POLL_SECONDS = 3
TIMEOUT_SECONDS = 240
# A task that forces the agent to actually run a shell command in the sandbox.
PROMPT = (
    "Run the shell command `uname -a && echo SANDBOX_OK && pwd` and then tell "
    "me, in one sentence, what kernel the sandbox reported."
)


def _need(var: str) -> str:
    val = os.environ.get(var)
    if not val:
        sys.exit(f"FAIL: environment variable {var} is not set. See the module docstring.")
    return val


def _summarise(event) -> str:
    """One readable line per session event."""
    t = getattr(event, "type", "?")
    # Pull the most informative field per event family without hard-coding every shape.
    for attr in ("text", "command", "name", "content", "message", "error", "status", "reason"):
        v = getattr(event, attr, None)
        if v:
            s = v if isinstance(v, str) else repr(v)
            return f"{t}: {s[:160]}"
    return t


def _ensure_agent(client, agent_id: str | None) -> str:
    """Return ``agent_id`` if set, otherwise create + return a minimal agent."""
    if agent_id:
        return agent_id
    print("CMA_AGENT_ID not set -- creating a minimal bash-capable agent...")
    agent = client.beta.agents.create(
        name="sandbox-skill-kit-e2e",
        model="claude-sonnet-4-6",
        system=(
            "You are a test agent. Use the bash tool to satisfy the user, "
            "then answer briefly."
        ),
        tools=[{"type": "agent_toolset_20260401"}],
    )
    print(f"  created agent {agent.id}")
    print(f"  (export CMA_AGENT_ID={agent.id} to reuse it next time)")
    return agent.id


def run(
    client,
    *,
    agent_id: str | None,
    environment_id: str,
    prompt: str = PROMPT,
    poll_seconds: float = POLL_SECONDS,
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> int:
    """Drive one Level 3 session and return the exit code.

    Extracted from ``main()`` so it can be exercised against a stubbed
    Anthropic client (see ``tests/test_e2e_dry_run.py``) -- which is how the
    orchestration logic is unit-tested without real CMA access.
    """
    agent_id = _ensure_agent(client, agent_id)

    print(f"\nCreating session: agent={agent_id} environment={environment_id}")
    session = client.beta.sessions.create(
        agent={"id": agent_id},
        environment_id=environment_id,
        title="sandbox-skill-kit Level 3 e2e",
    )
    print(f"  session {session.id} status={session.status}")
    print(
        "  -> this should trigger your Modal webhook now. "
        "Watch: modal app logs cma-self-hosted-sandboxes\n"
    )

    client.beta.sessions.events.send(
        session.id,
        events=[{"type": "user.message", "content": [{"type": "text", "text": prompt}]}],
    )
    print(f"Sent prompt: {prompt}\n")

    deadline = time.monotonic() + timeout_seconds
    last_status = None
    reached_terminal = False
    while time.monotonic() < deadline:
        s = client.beta.sessions.retrieve(session.id)
        if s.status != last_status:
            print(f"[status] {s.status}")
            last_status = s.status
        if s.status in ("idle", "terminated"):
            reached_terminal = True
            break
        time.sleep(poll_seconds)

    if not reached_terminal:
        print(
            f"\nFAIL: session did not reach idle within {timeout_seconds}s "
            f"(stuck at {last_status})."
        )
        print("Check `modal app logs cma-self-hosted-sandboxes` -- the webhook may not be firing.")
        return 1

    print("\n--- session transcript ---")
    tool_uses = 0
    errors = 0
    final_message = None
    for event in client.beta.sessions.events.list(session.id, order="asc"):
        print("  " + _summarise(event))
        et = getattr(event, "type", "")
        if "tool_use" in et:
            tool_uses += 1
        if "error" in et:
            errors += 1
        if et == "agent.message":
            final_message = _summarise(event)
    print("--- end transcript ---\n")

    print(f"agent tool-use events: {tool_uses}")
    print(f"error events:          {errors}")
    if final_message:
        print(f"final agent message:   {final_message}")

    if errors:
        print("\nFAIL: session reported error events. Inspect the transcript and Modal logs.")
        return 1
    if tool_uses == 0:
        print("\nFAIL: no agent tool-use events -- the sandbox never ran a tool. "
              "The webhook likely is not routing tool execution to Modal.")
        return 1

    print(
        "\nPASS: agent executed tools inside the self-hosted Modal sandbox "
        "and the session idled cleanly."
    )
    print(
        "Confirm the sandbox side too: `modal secret list --json` should now "
        "show a non-'-' Last used at,"
    )
    print(
        "and `modal app logs cma-self-hosted-sandboxes` should show "
        "[webhook] acked + [runner] lines."
    )
    return 0


def main() -> int:
    api_key = _need("ANTHROPIC_API_KEY")
    environment_id = _need("ANTHROPIC_ENVIRONMENT_ID")
    agent_id = os.environ.get("CMA_AGENT_ID")

    client = anthropic.Anthropic(api_key=api_key)
    return run(client, agent_id=agent_id, environment_id=environment_id)


if __name__ == "__main__":
    sys.exit(main())
