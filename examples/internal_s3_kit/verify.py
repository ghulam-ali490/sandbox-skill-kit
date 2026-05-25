"""Level-1 verification for the internal-object-store example.

No CMA account, no Modal deploy, no network, no real bucket. A seeded
in-memory store stands in for the object store so the wiring is confirmed
offline:

  1. Each custom tool exposes the expected name + a JSON input schema.
  2. The per-session factory returns the default toolset (bash, ...) PLUS
     the two custom tools.
  3. The tools list and fetch metadata correctly, including the empty
     prefix-match and missing-key branches -- exercised through the same
     ``.call(input)`` path the worker uses.

Run: python examples/internal_s3_kit/verify.py
"""
from __future__ import annotations

import asyncio
import sys

import internal_s3_tools
from anthropic.lib.tools.agent_toolset import AgentToolContext

import sandbox_runner

EXPECTED_CUSTOM = {"list_objects", "get_object_metadata"}


def _seeded_bucket() -> dict[str, dict]:
    return {
        "reports/2026-q1.pdf": {
            "size": 184_321,
            "content_type": "application/pdf",
            "modified": "2026-04-15T09:12:00Z",
        },
        "reports/2026-q2.pdf": {
            "size": 201_440,
            "content_type": "application/pdf",
            "modified": "2026-07-12T11:30:00Z",
        },
        "uploads/intake-form.json": {
            "size": 812,
            "content_type": "application/json",
            "modified": "2026-05-22T14:01:00Z",
        },
    }


def _install_seeded_bucket() -> None:
    """Point the tools at a seeded in-memory store instead of an empty one."""
    bucket = _seeded_bucket()
    internal_s3_tools._bucket = lambda: bucket


def main() -> int:
    ok = True
    _install_seeded_bucket()

    print("1. custom tool surface")
    for tool in internal_s3_tools.KIT_TOOLS:
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

    print("3. tools list/read the (seeded) bucket")
    res_list_all = asyncio.run(internal_s3_tools.list_objects.call({}))
    res_list_reports = asyncio.run(
        internal_s3_tools.list_objects.call({"prefix": "reports/"})
    )
    res_list_empty = asyncio.run(
        internal_s3_tools.list_objects.call({"prefix": "no-such/"})
    )
    res_meta_found = asyncio.run(
        internal_s3_tools.get_object_metadata.call({"key": "reports/2026-q1.pdf"})
    )
    res_meta_missing = asyncio.run(
        internal_s3_tools.get_object_metadata.call({"key": "missing.pdf"})
    )
    print(f"   list_objects()              -> {res_list_all!r}")
    print(f"   list_objects(reports/)      -> {res_list_reports!r}")
    print(f"   list_objects(no-such/)      -> {res_list_empty!r}")
    print(f"   get_object_metadata(found)  -> {res_meta_found!r}")
    print(f"   get_object_metadata(miss)   -> {res_meta_missing!r}")

    if "3 object(s)" not in str(res_list_all):
        ok = False
        print("     FAIL: empty-prefix listing did not include all 3 seeded keys")
    if "2 object(s)" not in str(res_list_reports) or "uploads/" in str(res_list_reports):
        ok = False
        print("     FAIL: prefix filter did not exclude non-matching keys")
    if "No objects with prefix" not in str(res_list_empty):
        ok = False
        print("     FAIL: empty-listing branch not handled")
    if "184321B" not in str(res_meta_found) or "application/pdf" not in str(res_meta_found):
        ok = False
        print("     FAIL: metadata fetch did not return size + content_type")
    if "No object found" not in str(res_meta_missing):
        ok = False
        print("     FAIL: missing-key branch not handled")

    print()
    if ok:
        print(
            "PASS: object-store migration wiring is correct. Same Phase 2 "
            "pattern as the other examples (keep worker(), pass "
            "tools=make_session_tools); swap _bucket() for an async S3 client "
            "(aiobotocore / aioboto3 / ...) to target a real backend."
        )
        return 0
    print("FAIL: see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
