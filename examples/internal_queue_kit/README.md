# Example: a kit backed by an internal message queue

A fourth worked **Phase 2** reference (see `../../docs/rollout.md`). Where
the other three examples cover bundled files
([`../internal_data_kit`](../internal_data_kit/README.md)), private HTTP APIs
([`../internal_api_kit`](../internal_api_kit/README.md)), and private
databases ([`../internal_db_kit`](../internal_db_kit/README.md)), this
example shows the fourth common shape: a kit whose tools push to and peek
at a **private message queue** (SQS / Redis Streams / NATS / RabbitMQ /
...) via a connection URL that lives only in your sandbox.

Use whichever example matches your kit:

| Your tools read from... | Copy this example |
| --- | --- |
| A bundled file / static dataset | `internal_data_kit` |
| A private HTTP API behind a token | `internal_api_kit` |
| A private database (Postgres, MySQL, sqlite, ...) | `internal_db_kit` |
| A private message queue (SQS / Redis / NATS / ...) | `internal_queue_kit` (this one) |

## The scenario

A kit whose agent enqueues jobs for downstream processing and reports on
what's pending on a channel. The connection URL never leaves the sandbox;
only the result strings go back to Claude.

## What is different from the other examples

The migration itself is identical: keep `worker()`, pass a `tools=` factory.
Two notes specific to a queue-backed kit:

1. **The connection URL comes from the sandbox environment.** A real
   `_store()` factory is built from one env var set on your Modal Secret:

   ```
   INTERNAL_QUEUE_URL  DSN / endpoint your client uses
                       (Redis URL, SQS queue URL, NATS server address, ...)
   ```

   When wiring into `modal_sandbox_webhook.py`, add the var to the sandbox
   `env` dict in `_create_sandbox` (read from the Modal Secret). See the
   header of `sandbox_runner.py` for the exact snippet.

2. **The store is injectable for testing.** Tools call a lazy `_store()`
   factory (`internal_queue_tools.py`). Tests swap in a seeded in-memory
   dict so the whole kit is verifiable with no network and no queue
   server.

This example uses a plain `dict[str, list[dict]]` to keep `verify.py`
runnable offline with zero new dependencies. A real kit swaps `_store()`
for an async queue client (e.g. `redis.asyncio.Redis.from_url(...)`,
`aiobotocore.session.get_session().create_client('sqs', ...)`,
`nats.connect(...)`); the worker wiring is unchanged.

## Files

- `internal_queue_tools.py` -- two queue-backed tools (`enqueue_job`, `peek_pending_jobs`) + a `KIT_TOOLS` export and the `_store()` factory
- `sandbox_runner.py` -- the migrated runner; identical to the base one except for `tools=`, plus a note on injecting the queue env var
- `verify.py` -- Level-1 check (no CMA/Modal/network/server): names, schemas, factory output, and live tool calls against a seeded in-memory store including the empty-channel branch and the limit clamp

## Verify it (no account, no network, no queue server)

```shell
cd examples/internal_queue_kit
python verify.py
```

Expected tail: `PASS: queue-backed migration wiring is correct.` It confirms
the factory returns the 6 default tools plus the 2 custom ones, and that the
tools push and peek correctly (including the empty branch and the limit
clamp).

## Going live (needs CMA access)

Same as the top-level README step 6, plus: set `INTERNAL_QUEUE_URL` (or
your client's preferred var name) on the Modal Secret, bundle
`internal_queue_tools.py` into the sandbox image, point the sandbox
entrypoint at this `sandbox_runner.py`, then drive a session that asks
e.g. "enqueue an invoice_send job for acct_42 on billing" -- the agent
calls `enqueue_job` against your real queue from inside your sandbox.
