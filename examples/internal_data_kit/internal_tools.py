"""Custom tools for the example "internal data" kit.

These stand in for tools that read data that must NOT leave your network. Here
the data is a local JSON file bundled into the sandbox image; in a real kit it
would be a private DB query or a call to an internal API. The point of adopting
sandbox-skill-kit is that this code runs inside YOUR Modal account, so the data
-- and any credential used to reach it -- never touches Anthropic.

Each tool is a plain async function decorated with ``beta_async_tool``. The
decorator infers the JSON input schema from the type hints and the docstring
``Args`` section, so the agent sees a well-described tool with no extra wiring.
"""
from __future__ import annotations

import json
from pathlib import Path

from anthropic.lib.tools import beta_async_tool

# In a real kit this Path would be a DB DSN / internal API base URL read from
# the sandbox's environment. A bundled file keeps the example self-contained.
_DATA_PATH = Path(__file__).with_name("internal_data.json")


def _load() -> dict:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


@beta_async_tool
async def lookup_order_status(order_id: str) -> str:
    """Look up the shipping status of an internal order.

    Args:
        order_id: Internal order id, e.g. "ORD-1001".
    """
    order = _load().get("orders", {}).get(order_id)
    if order is None:
        return f"No order found with id {order_id!r}."
    carrier = order.get("carrier") or "not yet assigned"
    eta = order.get("eta") or "unknown"
    return f"Order {order_id}: status={order['status']}, carrier={carrier}, eta={eta}."


@beta_async_tool
async def list_low_stock_skus(threshold: int = 5) -> str:
    """List internal warehouse SKUs at or below a stock threshold.

    Args:
        threshold: Stock level at or below which a SKU is reported (default 5).
    """
    inventory = _load().get("inventory", {})
    low = {sku: qty for sku, qty in inventory.items() if qty <= threshold}
    if not low:
        return f"No SKUs at or below {threshold} units."
    lines = ", ".join(f"{sku}={qty}" for sku, qty in sorted(low.items()))
    return f"Low-stock SKUs (<= {threshold}): {lines}."


# The tools this kit contributes to the sandbox worker. A real kit exports its
# tool objects here so the runner stays a thin wiring layer.
KIT_TOOLS = [lookup_order_status, list_low_stock_skus]
