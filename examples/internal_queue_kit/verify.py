"""Level-1 verification for the internal-queue example.

No CMA account, no Modal deploy, no network. A seeded in-memory store
stands in for the queue backend so the wiring is confirmed offline:

  1. Each custom tool exposes the expected name + a JSON input schema.
  2. The per-session factory returns the default toolset (bash, ...) PLUS
     the two custom tools.
  3. The tools push to and peek at the store correctly, including the
     "empty channel" branch and the limit clamp -- exercised through the
     same ``.call(input)`` path the worker uses.

Run: python examples/internal_queue_kit/verify.py
"""
from __future__ import annotations

import asyncio
import sys

import internal_queue_tools
from anthropic.lib.tools.agent_toolset import AgentToolContext

import sandbox_runner

EXPECTED_CUSTOM = {"enqueue_job", "peek_pending_jobs"}


def _seeded_store() -> dict[str, list[dict]]:
    return {
        "billing": [
            {"id": "job-0001", "payload": "invoice_send acct_42"},
            {"id": "job-0002", "payload": "invoice_send acct_43"},
        ],
        # 'idle' channel intentionally absent so the empty branch is reachable
    }


def _install_seeded_store() -> None:
    """Point the tools at a seeded in-memory store instead of an empty one."""
    store = _seeded_store()
    internal_queue_tools._store = lambda: store


def main() -> int:
    ok = True
    _install_seeded_store()

    print("1. custom tool surface")
    for tool in internal_queue_tools.KIT_TOOLS:
        schema = getattr(tool, "input_schema", None)
        props = list((schema or {}).get("properties", {}))
        print(f"   {tool.name!r}: properties={props}")
        if tool.name not in EXPECTED_CUSTOM:
            ok = False
            print(f"     FAIL: unexpected tool name {tool.name!r}")
        if not schema or schema.get("type") != "object":
            ok = False
            print("     FAIL: missing/invalid input schema")

    print("2. factory output (default toolset + custom)")
    ctx = AgentToolContext(workdir="/tmp", unrestricted_paths=True)
    tools = sandbox_runner.make_session_tools(ctx)
    names = [getattr(t, "name", "?") for t in tools]
    print(f"   {len(tools)} tools: {names}")
    if not EXPECTED_CUSTOM.issubset(names):
        ok = False
        print(f"     FAIL: custom tools missing: {EXPECTED_CUSTOM - set(names)}")
    if "bash" not in names:
        ok = False
        print("     FAIL: default toolset (expected a 'bash' tool) missing")

    print("3. tools push/peek the (seeded) queue")
    res_peek_billing = asyncio.run(
        internal_queue_tools.peek_pending_jobs.call({"channel": "billing"})
    )
    res_peek_idle = asyncio.run(
        internal_queue_tools.peek_pending_jobs.call({"channel": "idle"})
    )
    res_enqueue = asyncio.run(
        internal_queue_tools.enqueue_job.call(
            {"channel": "billing", "payload": "invoice_send acct_44"}
        )
    )
    res_peek_after = asyncio.run(
        internal_queue_tools.peek_pending_jobs.call({"channel": "billing", "limit": 5})
    )
    res_peek_limit = asyncio.run(
        internal_queue_tools.peek_pending_jobs.call({"channel": "billing", "limit": 1})
    )
    print(f"   peek_pending_jobs(billing)          -> {res_peek_billing!r}")
    print(f"   peek_pending_jobs(idle)             -> {res_peek_idle!r}")
    print(f"   enqueue_job(billing, ...)           -> {res_enqueue!r}")
    print(f"   peek_pending_jobs(billing, 5) after -> {res_peek_after!r}")
    print(f"   peek_pending_jobs(billing, 1)       -> {res_peek_limit!r}")
    if "depth=2" not in str(res_peek_billing) or "job-0001" not in str(res_peek_billing):
        ok = False
        print("     FAIL: peek did not summarise the seeded channel correctly")
    if "is empty" not in str(res_peek_idle):
        ok = False
        print("     FAIL: empty-channel branch not handled")
    if "job-0003" not in str(res_enqueue):
        ok = False
        print("     FAIL: enqueue did not generate the next sequential id")
    if "depth=3" not in str(res_peek_after):
        ok = False
        print("     FAIL: peek after enqueue did not reflect the new depth")
    if "job-0002" in str(res_peek_limit):
        ok = False
        print("     FAIL: limit=1 should clamp the summary to head only")

    print()
    if ok:
        print(
            "PASS: queue-backed migration wiring is correct. Same Phase 2 "
            "pattern as the other examples (keep worker(), pass "
            "tools=make_session_tools); swap _store() for an async queue "
            "client (redis.asyncio / aiobotocore / nats-py / ...) to target "
            "a real backend."
        )
        return 0
    print("FAIL: see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
