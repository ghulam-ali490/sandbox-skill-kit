"""Level-1 verification for the internal-DB example.

No CMA account, no Modal deploy, no network, no DB file on disk. An in-memory
sqlite database, seeded with a small fixture, stands in for the internal DB so
the wiring is confirmed offline:

  1. Each custom tool exposes the expected name + a JSON input schema.
  2. The per-session factory returns the default toolset (bash, ...) PLUS the
     two custom tools.
  3. The tools issue the right queries and shape the responses correctly,
     including the "not found" branch and the open/closed status filter --
     exercised through the same ``.call(input)`` path the worker uses.

Run: python examples/internal_db_kit/verify.py
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys

import internal_db_tools
from anthropic.lib.tools.agent_toolset import AgentToolContext

import sandbox_runner

EXPECTED_CUSTOM = {"get_employee", "list_open_incidents"}


def _seed_in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(
        """
        CREATE TABLE employees (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            department  TEXT NOT NULL,
            manager_id  TEXT
        );
        CREATE TABLE incidents (
            id        TEXT PRIMARY KEY,
            summary   TEXT NOT NULL,
            severity  TEXT NOT NULL,
            status    TEXT NOT NULL
        );
        INSERT INTO employees VALUES
            ('EMP-101', 'Alice Chen', 'Platform', 'EMP-001'),
            ('EMP-102', 'Bob Singh',  'Data',     'EMP-001');
        INSERT INTO incidents VALUES
            ('INC-1', 'Queue backed up',   'high', 'open'),
            ('INC-2', 'Disk near full',    'high', 'open'),
            ('INC-3', 'Old TLS cert warn', 'low',  'open'),
            ('INC-4', 'Migration failed',  'high', 'closed');
        """
    )
    conn.commit()
    return conn


def _install_seeded_conn() -> None:
    """Point the tools at an in-memory seeded sqlite instead of a real DB file."""
    conn = _seed_in_memory_db()
    internal_db_tools._conn = lambda: conn


def main() -> int:
    ok = True
    _install_seeded_conn()

    print("1. custom tool surface")
    for tool in internal_db_tools.KIT_TOOLS:
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

    print("3. tools query the (seeded) internal DB")
    res_found = asyncio.run(internal_db_tools.get_employee.call({"employee_id": "EMP-101"}))
    res_missing = asyncio.run(internal_db_tools.get_employee.call({"employee_id": "EMP-999"}))
    res_high = asyncio.run(internal_db_tools.list_open_incidents.call({"severity": "high"}))
    res_low = asyncio.run(internal_db_tools.list_open_incidents.call({"severity": "low"}))
    print(f"   get_employee(EMP-101)     -> {res_found!r}")
    print(f"   get_employee(EMP-999)     -> {res_missing!r}")
    print(f"   list_open_incidents(high) -> {res_high!r}")
    print(f"   list_open_incidents(low)  -> {res_low!r}")
    if "Alice Chen" not in str(res_found):
        ok = False
        print("     FAIL: employee lookup did not read DB row")
    if "No employee found" not in str(res_missing):
        ok = False
        print("     FAIL: not-found branch not handled")
    if "INC-1" not in str(res_high) or "INC-2" not in str(res_high):
        ok = False
        print("     FAIL: open high-severity filter did not return both expected rows")
    if "INC-4" in str(res_high):
        ok = False
        print("     FAIL: status=closed row leaked into open results")
    if "INC-3" not in str(res_low):
        ok = False
        print("     FAIL: low-severity filter did not return expected row")

    print()
    if ok:
        print(
            "PASS: DB-backed migration wiring is correct. Same Phase 2 pattern "
            "as the other examples (keep worker(), pass tools=make_session_tools); "
            "swap _conn() for an async driver (asyncpg/aiomysql/...) to target a "
            "real database."
        )
        return 0
    print("FAIL: see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
