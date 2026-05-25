"""Direct unit tests for the three Phase 2 example kits' tool functions.

Each example ships its own ``verify.py`` smoke script, but those print to
stdout and report success only via the exit code. This module covers the same
tool surfaces as proper pytest cases so CI flags regressions per-tool with a
real diff, not just "verify exit 1".

The example tool modules are loaded by file path under unique ``sys.modules``
names because:
  - the example directories are not Python packages and are not on sys.path,
    so a regular ``import`` would not find them, and
  - the three ``sandbox_runner.py`` files share a module name; importing them
    naively would collide.

Each fixture also installs the same offline backing the example's verify.py
uses (an httpx MockTransport for the API kit, an in-memory seeded sqlite for
the DB kit), so no network and no DB file on disk.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _load(unique_name: str, file_path: Path):
    """Import ``file_path`` as ``unique_name`` so cross-kit names cannot clash."""
    spec = importlib.util.spec_from_file_location(unique_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# internal_data_kit (bundled JSON file)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def data_tools():
    return _load(
        "ex_internal_data_tools",
        EXAMPLES / "internal_data_kit" / "internal_tools.py",
    )


async def test_data_lookup_order_shipped(data_tools):
    res = await data_tools.lookup_order_status.call({"order_id": "ORD-1001"})
    assert "shipped" in res
    assert "DHL" in res
    assert "2026-05-23" in res


async def test_data_lookup_order_null_carrier_and_eta(data_tools):
    # ORD-1002 has carrier=null + eta=null in the fixture; the tool should
    # fall back to the human-readable defaults, not leak "None".
    res = await data_tools.lookup_order_status.call({"order_id": "ORD-1002"})
    assert "processing" in res
    assert "not yet assigned" in res
    assert "unknown" in res
    assert "None" not in res


async def test_data_lookup_order_missing(data_tools):
    res = await data_tools.lookup_order_status.call({"order_id": "NOPE"})
    assert "No order found" in res


async def test_data_low_stock_default_threshold(data_tools):
    res = await data_tools.list_low_stock_skus.call({})
    # threshold defaults to 5 -> RED-01 (4) and BLU-02 (0) are low; BLK-04 (7) is not.
    assert "SKU-RED-01" in res
    assert "SKU-BLU-02" in res
    assert "SKU-BLK-04" not in res
    assert "SKU-GRN-03" not in res


async def test_data_low_stock_higher_threshold_includes_more(data_tools):
    res = await data_tools.list_low_stock_skus.call({"threshold": 10})
    # BLK-04 (7) is now under the threshold.
    assert "SKU-BLK-04" in res
    assert "SKU-GRN-03" not in res  # still well above


async def test_data_low_stock_empty_branch(data_tools):
    # No SKUs at or below 0 -> negative branch wording.
    res = await data_tools.list_low_stock_skus.call({"threshold": -1})
    assert "No SKUs at or below -1" in res


# --------------------------------------------------------------------------- #
# internal_api_kit (private HTTP API behind an httpx MockTransport)
# --------------------------------------------------------------------------- #
_FAKE_CUSTOMERS = {
    "CUST-42": {"name": "Acme Co", "tier": "gold", "open_tickets": 2},
}
_FAKE_TICKETS = [
    {"id": "TKT-1", "status": "open", "priority": "high"},
    {"id": "TKT-2", "status": "open", "priority": "low"},
    {"id": "TKT-3", "status": "closed", "priority": "low"},
]


def _api_handler(request: httpx.Request) -> httpx.Response:
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


@pytest.fixture(scope="module")
def api_tools():
    mod = _load(
        "ex_internal_api_tools",
        EXAMPLES / "internal_api_kit" / "internal_api_tools.py",
    )
    mock = httpx.AsyncClient(
        transport=httpx.MockTransport(_api_handler), base_url="http://internal.test"
    )
    mod._client = lambda: mock
    return mod


async def test_api_get_customer_found(api_tools):
    res = await api_tools.get_customer.call({"customer_id": "CUST-42"})
    assert "Acme Co" in res
    assert "gold" in res
    assert "open_tickets=2" in res


async def test_api_get_customer_404(api_tools):
    res = await api_tools.get_customer.call({"customer_id": "CUST-99"})
    assert "No customer found" in res


async def test_api_search_tickets_open_default(api_tools):
    res = await api_tools.search_tickets.call({})
    # default status="open" -> TKT-1 + TKT-2, NOT TKT-3 (closed).
    assert "2 open ticket(s)" in res
    assert "TKT-1(high)" in res
    assert "TKT-2(low)" in res
    assert "TKT-3" not in res


async def test_api_search_tickets_closed(api_tools):
    res = await api_tools.search_tickets.call({"status": "closed"})
    assert "1 closed ticket(s)" in res
    assert "TKT-3(low)" in res
    assert "TKT-1" not in res


async def test_api_search_tickets_empty_status(api_tools):
    # No tickets in this status -> negative branch wording.
    res = await api_tools.search_tickets.call({"status": "pending"})
    assert "No tickets with status 'pending'" in res


# --------------------------------------------------------------------------- #
# internal_db_kit (private DB; in-memory seeded sqlite stands in)
# --------------------------------------------------------------------------- #
def _seed_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(
        """
        CREATE TABLE employees (
            id TEXT PRIMARY KEY, name TEXT, department TEXT, manager_id TEXT
        );
        CREATE TABLE incidents (
            id TEXT PRIMARY KEY, summary TEXT, severity TEXT, status TEXT
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


@pytest.fixture(scope="module")
def db_tools():
    mod = _load(
        "ex_internal_db_tools",
        EXAMPLES / "internal_db_kit" / "internal_db_tools.py",
    )
    conn = _seed_db()
    mod._conn = lambda: conn
    return mod


async def test_db_get_employee_found(db_tools):
    res = await db_tools.get_employee.call({"employee_id": "EMP-101"})
    assert "Alice Chen" in res
    assert "Platform" in res
    assert "EMP-001" in res


async def test_db_get_employee_missing(db_tools):
    res = await db_tools.get_employee.call({"employee_id": "EMP-999"})
    assert "No employee found" in res


async def test_db_list_open_high_default(db_tools):
    # default severity="high" -> INC-1 + INC-2 (both open). INC-4 is high but
    # closed and must NOT appear.
    res = await db_tools.list_open_incidents.call({})
    assert "2 open high-severity incident(s)" in res
    assert "INC-1" in res
    assert "INC-2" in res
    assert "INC-4" not in res


async def test_db_list_open_low(db_tools):
    res = await db_tools.list_open_incidents.call({"severity": "low"})
    assert "1 open low-severity incident(s)" in res
    assert "INC-3" in res


async def test_db_list_open_unknown_severity(db_tools):
    res = await db_tools.list_open_incidents.call({"severity": "medium"})
    assert "No open incidents at severity 'medium'" in res


# --------------------------------------------------------------------------- #
# internal_queue_kit (private message queue; in-memory dict stands in)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="function")
def queue_tools():
    """Fresh seeded store per test so enqueue mutations don't bleed across cases."""
    mod = _load(
        "ex_internal_queue_tools",
        EXAMPLES / "internal_queue_kit" / "internal_queue_tools.py",
    )
    store: dict[str, list[dict]] = {
        "billing": [
            {"id": "job-0001", "payload": "invoice_send acct_42"},
            {"id": "job-0002", "payload": "invoice_send acct_43"},
        ],
    }
    mod._store = lambda: store
    return mod


async def test_queue_peek_seeded_channel(queue_tools):
    res = await queue_tools.peek_pending_jobs.call({"channel": "billing"})
    assert "depth=2" in res
    assert "job-0001" in res
    assert "job-0002" in res


async def test_queue_peek_empty_channel(queue_tools):
    res = await queue_tools.peek_pending_jobs.call({"channel": "no-such"})
    assert "is empty" in res


async def test_queue_peek_default_channel(queue_tools):
    # default channel name is "default" which is absent in the fixture -> empty branch
    res = await queue_tools.peek_pending_jobs.call({})
    assert "Channel 'default' is empty" in res


async def test_queue_peek_respects_limit(queue_tools):
    res = await queue_tools.peek_pending_jobs.call({"channel": "billing", "limit": 1})
    assert "job-0001" in res
    assert "job-0002" not in res


async def test_queue_enqueue_generates_sequential_id(queue_tools):
    res = await queue_tools.enqueue_job.call(
        {"channel": "billing", "payload": "invoice_send acct_44"}
    )
    assert "job-0003" in res
    assert "depth=3" in res


async def test_queue_enqueue_creates_new_channel(queue_tools):
    res = await queue_tools.enqueue_job.call(
        {"channel": "video-encode", "payload": "render fhd"}
    )
    assert "job-0001" in res  # first job on a fresh channel
    assert "depth=1" in res
    # Confirm a subsequent peek sees it.
    peek = await queue_tools.peek_pending_jobs.call({"channel": "video-encode"})
    assert "depth=1" in peek
    assert "render fhd" in peek


# --------------------------------------------------------------------------- #
# internal_s3_kit (private object store; in-memory dict stands in)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def s3_tools():
    mod = _load(
        "ex_internal_s3_tools",
        EXAMPLES / "internal_s3_kit" / "internal_s3_tools.py",
    )
    bucket: dict[str, dict] = {
        "reports/2026-q1.pdf": {
            "size": 184_321,
            "content_type": "application/pdf",
            "modified": "2026-04-15T09:12:00Z",
        },
        "uploads/intake-form.json": {
            "size": 812,
            "content_type": "application/json",
            "modified": "2026-05-22T14:01:00Z",
        },
    }
    mod._bucket = lambda: bucket
    return mod


async def test_s3_list_all(s3_tools):
    res = await s3_tools.list_objects.call({})
    assert "2 object(s)" in res
    assert "reports/2026-q1.pdf" in res
    assert "uploads/intake-form.json" in res


async def test_s3_list_with_prefix(s3_tools):
    res = await s3_tools.list_objects.call({"prefix": "reports/"})
    assert "reports/2026-q1.pdf" in res
    assert "uploads/intake-form.json" not in res


async def test_s3_list_empty_prefix_match(s3_tools):
    res = await s3_tools.list_objects.call({"prefix": "no-such/"})
    assert "No objects with prefix" in res


async def test_s3_get_metadata_found(s3_tools):
    res = await s3_tools.get_object_metadata.call({"key": "reports/2026-q1.pdf"})
    assert "184321B" in res
    assert "application/pdf" in res


async def test_s3_get_metadata_missing(s3_tools):
    res = await s3_tools.get_object_metadata.call({"key": "nope.bin"})
    assert "No object found" in res
