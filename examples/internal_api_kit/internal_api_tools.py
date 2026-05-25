"""Custom tools for an example kit backed by an INTERNAL HTTP API.

The other example (``../internal_data_kit``) bundles a JSON file. A real kit
more often reaches a *private service*: a DB behind an internal HTTP API, a
microservice, etc. This example shows that pattern.

The point of running inside your own Modal sandbox is that the API's base URL
and bearer token come from the **sandbox environment**, so the credential is
set once on the Modal Secret and never touches Anthropic. The tools call the
internal API; only the model-facing *result strings* go back to Claude.

Environment contract (injected into the sandbox alongside the env key):
  INTERNAL_API_BASE_URL  - base URL of the internal service
  INTERNAL_API_TOKEN     - bearer token for that service (sandbox-only)

The client is built lazily via ``_client()`` so tests can swap in an httpx
``MockTransport`` and verify the wiring with no network. ``anthropic`` already
depends on ``httpx``, so this adds no new runtime dependency.
"""
from __future__ import annotations

import os
from functools import lru_cache

import httpx
from anthropic.lib.tools import beta_async_tool


@lru_cache
def _client() -> httpx.AsyncClient:
    """Lazy, cached client built from the sandbox env. Tests monkeypatch this
    function to inject an httpx ``MockTransport``."""
    base_url = os.environ.get("INTERNAL_API_BASE_URL", "https://internal.invalid")
    token = os.environ.get("INTERNAL_API_TOKEN", "")
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"} if token else {},
        timeout=10.0,
    )


@beta_async_tool
async def get_customer(customer_id: str) -> str:
    """Fetch an internal customer record by id.

    Args:
        customer_id: Internal customer id, e.g. "CUST-42".

    Returns:
        One-line summary with name, tier, and open ticket count, or a not-found message.
    """
    resp = await _client().get(f"/customers/{customer_id}")
    if resp.status_code == 404:
        return f"No customer found with id {customer_id!r}."
    resp.raise_for_status()
    c = resp.json()
    return (
        f"Customer {customer_id}: name={c['name']}, tier={c['tier']}, "
        f"open_tickets={c['open_tickets']}."
    )


@beta_async_tool
async def search_tickets(status: str = "open") -> str:
    """Search internal support tickets by status.

    Args:
        status: Ticket status to filter by, e.g. "open" or "closed". Default "open".

    Returns:
        Count + comma-separated "id(priority)" list, or a no-match message.
    """
    resp = await _client().get("/tickets", params={"status": status})
    resp.raise_for_status()
    tickets = resp.json().get("tickets", [])
    if not tickets:
        return f"No tickets with status {status!r}."
    lines = ", ".join(f"{t['id']}({t['priority']})" for t in tickets)
    return f"{len(tickets)} {status} ticket(s): {lines}."


# The tools this kit contributes to the sandbox worker.
KIT_TOOLS = [get_customer, search_tickets]
