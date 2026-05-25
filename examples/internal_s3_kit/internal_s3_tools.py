"""Custom tools for an example kit backed by an internal OBJECT STORE.

The other four examples cover bundled-file (`internal_data_kit`), private
HTTP API (`internal_api_kit`), private database (`internal_db_kit`), and
private message queue (`internal_queue_kit`). This example shows the fifth
common shape: a kit whose tools read from a **private object store** (S3 /
GCS / Cloudflare R2 / self-hosted MinIO / ...) via a bucket name + creds
that live only in the sandbox.

The example uses a `dict[str, dict]` keyed by object key as the in-memory
backing so the pattern is verifiable offline with zero new runtime dep. A
real kit swaps `_bucket()` for an async S3 client factory (e.g.
`aiobotocore.session.get_session().create_client('s3', ...)`); the worker
wiring is unchanged.

Environment contract (injected into the sandbox alongside the env key):
  INTERNAL_S3_BUCKET   - bucket name your tools read from
  INTERNAL_S3_REGION   - region (or endpoint URL for non-AWS providers)
  INTERNAL_S3_ACCESS_KEY / INTERNAL_S3_SECRET_KEY - credentials

This example does not read those env vars (the in-memory store needs no
config), but they are documented so real kits keep the same
env-as-credential discipline as the other examples.
"""
from __future__ import annotations

from functools import lru_cache

from anthropic.lib.tools import beta_async_tool


@lru_cache
def _bucket() -> dict[str, dict]:
    """Lazy, cached in-memory object store. Tests monkeypatch this function
    to inject a pre-seeded bucket.

    A real kit replaces this with an async S3 client factory, e.g.::

        @lru_cache
        def _bucket():
            session = aiobotocore.session.get_session()
            return session.create_client(
                's3',
                region_name=os.environ['INTERNAL_S3_REGION'],
                aws_access_key_id=os.environ['INTERNAL_S3_ACCESS_KEY'],
                aws_secret_access_key=os.environ['INTERNAL_S3_SECRET_KEY'],
            )
    """
    return {}


@beta_async_tool
async def list_objects(prefix: str = "") -> str:
    """List internal object keys matching a prefix.

    Args:
        prefix: Key prefix to match. Default "" (all keys).

    Returns:
        Count + comma-separated "key (sizeB)" list, or a no-match message.
    """
    matches = sorted(k for k in _bucket() if k.startswith(prefix))
    if not matches:
        return f"No objects with prefix {prefix!r}."
    lines = ", ".join(f"{k} ({_bucket()[k]['size']}B)" for k in matches)
    return f"{len(matches)} object(s) with prefix {prefix!r}: {lines}."


@beta_async_tool
async def get_object_metadata(key: str) -> str:
    """Fetch metadata for one internal object.

    Args:
        key: Full object key, e.g. "reports/2026-q1.pdf".

    Returns:
        One-line summary with size, content_type, and modified timestamp, or a not-found message.
    """
    obj = _bucket().get(key)
    if obj is None:
        return f"No object found at key {key!r}."
    return (
        f"Object {key}: size={obj['size']}B, "
        f"content_type={obj['content_type']}, modified={obj['modified']}."
    )


# The tools this kit contributes to the sandbox worker.
KIT_TOOLS = [list_objects, get_object_metadata]
