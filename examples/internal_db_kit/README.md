# Example: a kit backed by an internal database

A third worked **Phase 2** reference (see `../../docs/rollout.md`). Where
[`../internal_data_kit`](../internal_data_kit/README.md) bundles a JSON file
and [`../internal_api_kit`](../internal_api_kit/README.md) calls a private HTTP
API, this example shows the third common shape: a kit whose tools query a
**private database** directly with a DSN that lives only in your sandbox.

Use whichever example matches your kit:

| Your tools read from... | Copy this example |
| --- | --- |
| A bundled file / static dataset | `internal_data_kit` |
| A private HTTP API behind a token | `internal_api_kit` |
| A private database (Postgres, MySQL, sqlite, ...) | `internal_db_kit` (this one) |

## The scenario

A kit whose agent answers questions about **internal employees and incidents**
held in a private database. The DSN never leaves the sandbox; only the result
strings go back to Claude.

## What is different from the other examples

The migration itself is identical: keep `worker()`, pass a `tools=` factory.
Two notes specific to a DB-backed kit:

1. **The DSN comes from the sandbox environment.** The connection is built
   from one env var set on your Modal Secret:

   ```
   INTERNAL_DB_PATH   sqlite path (this example) -- swap to your driver's DSN
                      env var name when targeting Postgres/MySQL/etc.
   ```

   When wiring into `modal_sandbox_webhook.py`, add the var to the sandbox
   `env` dict in `_create_sandbox` (read from the Modal Secret). See the
   header of `sandbox_runner.py` for the exact snippet.

2. **The connection is injectable for testing.** Tools call a lazy `_conn()`
   factory (`internal_db_tools.py`). Tests swap in an in-memory seeded sqlite
   so the whole kit is verifiable with no DB file on disk and no network.

This example uses stdlib `sqlite3` to keep `verify.py` runnable offline with
zero new dependencies. The blocking sqlite calls are wrapped in
`asyncio.to_thread` so the tool signatures are honestly async. A real kit
typically swaps `_conn()` for an async driver (`asyncpg` for Postgres,
`aiomysql` for MySQL, etc.); the worker wiring is unchanged.

## Files

- `internal_db_tools.py` -- two DB-backed tools (`get_employee`, `list_open_incidents`) + a `KIT_TOOLS` export and the `_conn()` factory
- `sandbox_runner.py` -- the migrated runner; identical to the base one except for `tools=`, plus a note on injecting the DB env var
- `verify.py` -- Level-1 check (no CMA/Modal/network/file): names, schemas, factory output, and live tool calls against an in-memory seeded sqlite including the not-found and open/closed branches

## Verify it (no account, no network, no DB file)

```shell
cd examples/internal_db_kit
python verify.py
```

Expected tail: `PASS: DB-backed migration wiring is correct.` It confirms the
factory returns the 6 default tools plus the 2 custom ones, and that the tools
issue the right queries and shape the responses (including "not found" and
the open/closed status filter).

## Going live (needs CMA access)

Same as the top-level README step 6, plus: set `INTERNAL_DB_PATH` (or your
driver's DSN var) on the Modal Secret, bundle `internal_db_tools.py` into the
sandbox image, point the sandbox entrypoint at this `sandbox_runner.py`, then
drive a session that asks e.g. "who is employee EMP-101?" -- the agent calls
`get_employee` against your DB from inside your sandbox.
