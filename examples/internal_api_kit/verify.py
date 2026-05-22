"""Level-1 verification for the internal-API example.

No CMA account, no Modal deploy, and no network. An httpx ``MockTransport``
stands in for the internal API, so the wiring is confirmed offline:

  1. Each custom tool exposes the expected name + a JSON input schema.
  2. The per-session factory returns the default toolset (bash, ...) PLUS the
     two custom tools.
  3. The tools issue the right HTTP calls and shape the responses correctly,
     including the 404 "not found" branch -- exercised through the same
     ``.call(input)`` path the worker uses.

Run: python examples/internal_api_kit/verify.py
"""
from __future__ import annotations

import asyncio
import sys

import httpx
import internal_api_tools
from anthropic.lib.tools.agent_toolset import AgentToolContext

import sandbox_runner

EXPECTED_CUSTOM = {"get_customer", "search_tickets"}

# Fake internal API data the MockTransport serves.
_FAKE_CUSTOMERS = {
    "CUST-42": {"name": "Acme Co", "tier": "gold", "open_tickets": 2},
}
_FAKE_TICKETS = [
    {"id": "TKT-1", "status": "open", "priority": "high"},
    {"id": "TKT-2", "status": "open", "priority": "low"},
    {"id": "TKT-3", "status": "closed", "priority": "low"},
]


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith("/customers/"):
        cid = path.rsplit("/", 1)[-1]
        customer = _FAKE_CUSTOMERS.get(cid)
        if customer is None:
            return httpx.Response(404)
        return httpx.Response(200, json=customer)
    if path == "/tickets":
        status = request.url.params.get("status", "open")
        tickets = [t for t in _FAKE_TICKETS if t["status"] == status]
        return httpx.Response(200, json={"tickets": tickets})
    return httpx.Response(404)


def _install_mock_client() -> None:
    """Point the tools at the MockTransport instead of a real internal API."""
    mock = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), base_url="http://internal.test"
    )
    internal_api_tools._client = lambda: mock


def main() -> int:
    ok = True
    _install_mock_client()

    print("1. custom tool surface")
    for tool in internal_api_tools.KIT_TOOLS:
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

    print("3. tools call the (mocked) internal API")
    res_found = asyncio.run(internal_api_tools.get_customer.call({"customer_id": "CUST-42"}))
    res_missing = asyncio.run(internal_api_tools.get_customer.call({"customer_id": "CUST-99"}))
    res_tickets = asyncio.run(internal_api_tools.search_tickets.call({"status": "open"}))
    print(f"   get_customer(CUST-42) -> {res_found!r}")
    print(f"   get_customer(CUST-99) -> {res_missing!r}")
    print(f"   search_tickets(open)  -> {res_tickets!r}")
    if "Acme Co" not in str(res_found):
        ok = False
        print("     FAIL: customer lookup did not parse the API response")
    if "No customer found" not in str(res_missing):
        ok = False
        print("     FAIL: 404 branch not handled")
    if "TKT-1" not in str(res_tickets) or "2 open" not in str(res_tickets):
        ok = False
        print("     FAIL: ticket search did not filter/shape correctly")

    print()
    if ok:
        print(
            "PASS: API-backed migration wiring is correct. Same Phase 2 pattern "
            "as internal_data_kit (keep worker(), pass tools=make_session_tools); "
            "the only addition is reaching an internal API via env-configured creds."
        )
        return 0
    print("FAIL: see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
