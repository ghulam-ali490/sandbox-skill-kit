# Example: a kit backed by an internal object store

A fifth worked **Phase 2** reference (see `../../docs/rollout.md`). Where
the other four examples cover bundled files
([`../internal_data_kit`](../internal_data_kit/README.md)), private HTTP
APIs ([`../internal_api_kit`](../internal_api_kit/README.md)), private
databases ([`../internal_db_kit`](../internal_db_kit/README.md)), and
private message queues
([`../internal_queue_kit`](../internal_queue_kit/README.md)), this example
shows the fifth common shape: a kit whose tools read from a **private
object store** (S3 / GCS / Cloudflare R2 / self-hosted MinIO / ...) via a
bucket name + credentials that live only in your sandbox.

Use whichever example matches your kit:

| Your tools read from... | Copy this example |
| --- | --- |
| A bundled file / static dataset | `internal_data_kit` |
| A private HTTP API behind a token | `internal_api_kit` |
| A private database (Postgres, MySQL, sqlite, ...) | `internal_db_kit` |
| A private message queue (SQS / Redis / NATS / ...) | `internal_queue_kit` |
| A private object store (S3 / GCS / R2 / MinIO / ...) | `internal_s3_kit` (this one) |

## The scenario

A kit whose agent lists pending uploads and fetches metadata about reports
held in a private bucket. The credentials never leave the sandbox; only the
result strings go back to Claude.

## What is different from the other examples

The migration itself is identical: keep `worker()`, pass a `tools=` factory.
Two notes specific to an object-store kit:

1. **The bucket + credentials come from the sandbox environment.** A real
   `_bucket()` factory is built from these env vars on your Modal Secret:

   ```
   INTERNAL_S3_BUCKET       bucket name your tools read from
   INTERNAL_S3_REGION       region (or endpoint URL for non-AWS providers)
   INTERNAL_S3_ACCESS_KEY   access key id
   INTERNAL_S3_SECRET_KEY   secret access key
   ```

   When wiring into `modal_sandbox_webhook.py`, add the vars to the
   sandbox `env` dict in `_create_sandbox` (read from the Modal Secret).
   See the header of `sandbox_runner.py` for the exact snippet.

2. **The bucket factory is injectable for testing.** Tools call a lazy
   `_bucket()` factory (`internal_s3_tools.py`). Tests swap in a seeded
   in-memory dict so the whole kit is verifiable with no network and no
   real bucket.

This example uses a plain `dict[str, dict]` to keep `verify.py` runnable
offline with zero new dependencies. A real kit swaps `_bucket()` for an
async S3 client factory (e.g. `aiobotocore`, `aioboto3`); the worker
wiring is unchanged.

## Files

- `internal_s3_tools.py` -- two object-store tools (`list_objects`, `get_object_metadata`) + a `KIT_TOOLS` export and the `_bucket()` factory
- `sandbox_runner.py` -- the migrated runner; identical to the base one except for `tools=`, plus a note on injecting the bucket env vars
- `verify.py` -- Level-1 check (no CMA/Modal/network/bucket): names, schemas, factory output, and live tool calls against a seeded in-memory store including the empty-prefix and missing-key branches

## Verify it (no account, no network, no bucket)

```shell
cd examples/internal_s3_kit
python verify.py
```

Expected tail: `PASS: object-store migration wiring is correct.` It
confirms the factory returns the 6 default tools plus the 2 custom ones,
and that the tools list and fetch metadata correctly (including empty and
missing branches).

## Going live (needs CMA access)

Same as the top-level README step 6, plus: set the four `INTERNAL_S3_*`
vars on the Modal Secret, bundle `internal_s3_tools.py` into the sandbox
image, point the sandbox entrypoint at this `sandbox_runner.py`, then
drive a session that asks e.g. "list pending uploads" -- the agent calls
`list_objects` against your real bucket from inside your sandbox.
