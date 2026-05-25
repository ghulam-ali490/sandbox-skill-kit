"""Custom tools for an example kit backed by an internal MESSAGE QUEUE.

The other three examples cover bundled-file (`internal_data_kit`), private
HTTP API (`internal_api_kit`), and private database (`internal_db_kit`).
This example shows the fourth common shape: a kit whose tools push to and
peek at a **private message queue** (SQS / Redis / NATS / RabbitMQ / ...)
via a connection URL that lives only in the sandbox.

The example uses an in-memory `dict[str, list[dict]]` keyed by channel so
the pattern is verifiable offline with zero new runtime dependency. A real
kit swaps `_store()` for a queue-client factory (e.g. `aiobotocore` for SQS,
`redis.asyncio` for Redis Streams, `nats-py` for NATS); the worker wiring
is unchanged.

Environment contract (injected into the sandbox alongside the env key):
  INTERNAL_QUEUE_URL  - DSN / endpoint your queue client uses. For sqs this
                        is the queue URL, for redis it's the connection URL,
                        for nats it's the server address. This example does
                        not read it (the in-memory store needs no config),
                        but the variable is documented so real kits keep the
                        same env-as-credential discipline as the other examples.

Tools are async by design even though the in-memory store is sync, because
real queue clients are async and the agent expects the same surface for both.
"""
from __future__ import annotations

from functools import lru_cache

from anthropic.lib.tools import beta_async_tool


@lru_cache
def _store() -> dict[str, list[dict]]:
    """Lazy, cached in-memory queue store keyed by channel. Tests monkeypatch
    this function to inject a pre-seeded store.

    A real kit replaces this with a queue-client factory (asyncio singleton,
    e.g. ``redis.asyncio.Redis.from_url(os.environ['INTERNAL_QUEUE_URL'])``).
    """
    return {}


@beta_async_tool
async def enqueue_job(channel: str, payload: str) -> str:
    """Push a job onto an internal channel.

    Args:
        channel: Channel name, e.g. "billing" or "video-encode".
        payload: Opaque job payload (the consumer interprets it).

    Returns:
        Confirmation with the new sequential job id and the updated channel depth.
    """
    queue = _store().setdefault(channel, [])
    job_id = f"job-{len(queue) + 1:04d}"
    queue.append({"id": job_id, "payload": payload})
    return f"Enqueued {job_id} on channel {channel!r} (depth={len(queue)})."


@beta_async_tool
async def peek_pending_jobs(channel: str = "default", limit: int = 5) -> str:
    """Peek at the next pending jobs on a channel without consuming.

    Args:
        channel: Channel name to peek. Default "default".
        limit: Max number of jobs to include in the summary. Default 5.

    Returns:
        Channel depth + head-of-queue "id(payload)" summary, or an empty-channel message.
    """
    queue = _store().get(channel, [])
    if not queue:
        return f"Channel {channel!r} is empty."
    head = queue[:limit]
    lines = ", ".join(f"{j['id']}({j['payload']})" for j in head)
    return f"Channel {channel!r} depth={len(queue)}, head: {lines}."


# The tools this kit contributes to the sandbox worker.
KIT_TOOLS = [enqueue_job, peek_pending_jobs]
