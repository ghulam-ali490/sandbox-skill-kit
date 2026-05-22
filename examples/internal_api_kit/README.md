# Example: a kit backed by an internal HTTP API

A second worked **Phase 2** reference (see `../../docs/rollout.md`). Where
[`../internal_data_kit`](../internal_data_kit/README.md) bundles a JSON file,
this example shows the more common real-world shape: a kit whose tools call a
**private HTTP API** (a service in front of a DB, an internal microservice,
etc.) using a credential that lives only in your sandbox.

Use whichever example matches your kit:

| Your tools read from... | Copy this example |
| --- | --- |
| A bundled file / static dataset | `internal_data_kit` |
| A private DB or internal HTTP API behind a token | `internal_api_kit` (this one) |

## The scenario

A kit whose agent answers questions about **internal customers and support
tickets** held in a private service. The agent must never get the service
token; only the resulting answer strings go back to Claude.

## What is different from internal_data_kit

The migration itself is identical: keep `worker()`, pass a `tools=` factory.
Two additions specific to an API-backed kit:

1. **Credentials come from the sandbox environment**, not a bundled file. The
   client is built from two env vars set on your Modal Secret:

   ```
   INTERNAL_API_BASE_URL   base URL of the internal service
   INTERNAL_API_TOKEN      bearer token (sandbox-only; never reaches Anthropic)
   ```

   When wiring into `modal_sandbox_webhook.py`, add these to the sandbox `env`
   dict in `_create_sandbox` (read from the Modal Secret). See the header of
   `sandbox_runner.py` for the exact snippet.

2. **The client is injectable for testing.** Tools call a lazy `_client()`
   factory (`internal_api_tools.py`). Tests swap in an httpx `MockTransport`,
   so the whole kit is verifiable with no network and no real API. `anthropic`
   already depends on `httpx`, so this adds no runtime dependency.

## Files

- `internal_api_tools.py` -- two API-backed tools (`get_customer`, `search_tickets`) + a `KIT_TOOLS` export and the `_client()` factory
- `sandbox_runner.py` -- the migrated runner; identical to the base one except for `tools=`, plus a note on injecting the API env vars
- `verify.py` -- Level-1 check (no CMA/Modal/network): names, schemas, factory output, and live tool calls against a mocked API including the 404 branch

## Verify it (no account, no network)

```shell
cd examples/internal_api_kit
python verify.py
```

Expected tail: `PASS: API-backed migration wiring is correct.` It confirms the
factory returns the 6 default tools plus the 2 custom ones, and that the tools
issue the right HTTP calls and shape the responses (including "not found").

## Going live (needs CMA access)

Same as the top-level README step 6, plus: set `INTERNAL_API_BASE_URL` and
`INTERNAL_API_TOKEN` on the Modal Secret, bundle `internal_api_tools.py` into
the sandbox image, point the sandbox entrypoint at this `sandbox_runner.py`,
then drive a session that asks e.g. "what tier is customer CUST-42?" -- the
agent calls `get_customer` against your internal API from inside your sandbox.
