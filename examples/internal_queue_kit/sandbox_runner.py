"""Example sandbox runner for a kit backed by an internal MESSAGE QUEUE.

Same shape as the other three examples (`../internal_data_kit/`,
`../internal_api_kit/`, `../internal_db_kit/`): the only kit-specific change
is the ``tools=`` factory. As with the API and DB examples, the sandbox
needs the queue connection info in its environment.

When you wire this into ``modal_sandbox_webhook.py``, add the DSN var to the
sandbox ``env`` dict in ``_create_sandbox`` (read from the Modal Secret), e.g.::

    env={
        ...,
        "INTERNAL_QUEUE_URL": os.environ["INTERNAL_QUEUE_URL"],
    }

so ``internal_queue_tools._store()`` (in a real kit) can construct an
authenticated queue client. The URL lives only in your Modal Secret and
inside the sandbox; it never reaches Anthropic.

For a real queue backend (Redis Streams / SQS / NATS / RabbitMQ), swap
``_store()`` in ``internal_queue_tools.py`` for an async client factory and
rename the env var accordingly; the worker wiring below is unchanged.
"""
import asyncio
import logging
import os
import sys

from anthropic import AsyncAnthropic
from anthropic.lib.tools.agent_toolset import (
    AgentToolContext,
    beta_agent_toolset_20260401,
)

from internal_queue_tools import KIT_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="[runner] %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

WORKDIR = "/workspace"


def make_session_tools(ctx: AgentToolContext):
    """Per-session factory: built-in toolset bound to this session's context,
    plus this kit's queue-backed tools. The custom tools reach the queue via
    the env-configured URL, so they need no ``ctx``."""
    return [*beta_agent_toolset_20260401(ctx), *KIT_TOOLS]


async def main() -> None:
    environment_key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
    async with AsyncAnthropic(auth_token=environment_key) as client:
        await client.beta.environments.work.worker(
            environment_key=environment_key,
            tools=make_session_tools,
            workdir=WORKDIR,
            unrestricted_paths=True,
        ).handle_item()


if __name__ == "__main__":
    asyncio.run(main())
