"""Level-1 verification for the internal-data example.

No CMA account and no Modal deploy needed. Confirms the migration wiring is
correct so a kit author can trust the pattern before paying for any infra:

  1. Each custom tool imports and exposes the expected name + a JSON input schema.
  2. The per-session factory returns the default toolset (bash, ...) PLUS the
     two custom tools.
  3. The custom tools actually return data from the bundled internal file when
     invoked through the same ``.call(input)`` path the worker uses.

Run: python examples/internal_data_kit/verify.py
"""
from __future__ import annotations

import asyncio
import sys

from anthropic.lib.tools.agent_toolset import AgentToolContext

import internal_tools
import sandbox_runner

EXPECTED_CUSTOM = {"lookup_order_status", "list_low_stock_skus"}


def main() -> int:
    ok = True

    print("1. custom tool surface")
    for tool in internal_tools.KIT_TOOLS:
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

    print("3. tools return internal data")
    res_order = asyncio.run(internal_tools.lookup_order_status.call({"order_id": "ORD-1001"}))
    res_stock = asyncio.run(internal_tools.list_low_stock_skus.call({"threshold": 5}))
    print(f"   lookup_order_status -> {res_order!r}")
    print(f"   list_low_stock_skus -> {res_stock!r}")
    if "shipped" not in str(res_order):
        ok = False
        print("     FAIL: order lookup did not read bundled data")
    if "SKU-BLU-02" not in str(res_stock):
        ok = False
        print("     FAIL: low-stock lookup did not read bundled data")

    print()
    if ok:
        print("PASS: migration wiring is correct. This is the Phase 2 pattern any "
              "tool-bearing kit follows: keep worker(), pass tools=make_session_tools.")
        return 0
    print("FAIL: see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
