"""Custom tools for an example kit backed by an internal DATABASE.

The other examples bundle a JSON file (``internal_data_kit``) or call a private
HTTP API (``internal_api_kit``). This example shows the third common shape: a
kit whose tools query a **private database** directly using a DSN that lives
only in the sandbox.

This example uses stdlib ``sqlite3`` so the pattern is verifiable offline with
no new runtime dependency. A real kit typically swaps ``_conn()`` for an async
driver (``asyncpg`` for Postgres, ``aiomysql`` for MySQL, etc.) -- everything
else (env-configured DSN, injectable factory, model-facing string results)
stays identical. The blocking sqlite calls are wrapped in ``asyncio.to_thread``
so the tool signatures are honestly async even with the stdlib driver.

Environment contract (injected into the sandbox alongside the env key):
  INTERNAL_DB_PATH  - filesystem path to the sqlite database inside the sandbox.
                      For non-sqlite drivers, replace with the DSN env var your
                      driver expects (e.g. INTERNAL_DB_DSN for asyncpg).
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from functools import lru_cache

from anthropic.lib.tools import beta_async_tool


@lru_cache
def _conn() -> sqlite3.Connection:
    """Lazy, cached connection built from the sandbox env. Tests monkeypatch
    this function to inject an in-memory seeded sqlite connection.

    ``check_same_thread=False`` lets ``asyncio.to_thread`` workers share one
    connection; sqlite3 itself serialises access at the connection level.
    """
    path = os.environ.get("INTERNAL_DB_PATH", "/sandbox/internal.db")
    return sqlite3.connect(path, check_same_thread=False)


def _query_one(sql: str, params: tuple) -> tuple | None:
    cur = _conn().execute(sql, params)
    try:
        return cur.fetchone()
    finally:
        cur.close()


def _query_all(sql: str, params: tuple) -> list[tuple]:
    cur = _conn().execute(sql, params)
    try:
        return cur.fetchall()
    finally:
        cur.close()


@beta_async_tool
async def get_employee(employee_id: str) -> str:
    """Look up an internal employee record by id.

    Args:
        employee_id: Internal employee id, e.g. "EMP-101".
    """
    row = await asyncio.to_thread(
        _query_one,
        "SELECT name, department, manager_id FROM employees WHERE id = ?",
        (employee_id,),
    )
    if row is None:
        return f"No employee found with id {employee_id!r}."
    name, department, manager_id = row
    return (
        f"Employee {employee_id}: name={name}, dept={department}, "
        f"manager={manager_id}."
    )


@beta_async_tool
async def list_open_incidents(severity: str = "high") -> str:
    """List open internal incidents at a given severity.

    Args:
        severity: Severity to filter by, e.g. "high", "medium", "low". Default "high".
    """
    rows = await asyncio.to_thread(
        _query_all,
        "SELECT id, summary FROM incidents WHERE status = 'open' AND severity = ?",
        (severity,),
    )
    if not rows:
        return f"No open incidents at severity {severity!r}."
    lines = ", ".join(f"{iid}({summary})" for iid, summary in rows)
    return f"{len(rows)} open {severity}-severity incident(s): {lines}."


# The tools this kit contributes to the sandbox worker.
KIT_TOOLS = [get_employee, list_open_incidents]
