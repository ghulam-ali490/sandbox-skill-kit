"""Example sandbox runner for a kit backed by an internal HTTP API.

Same shape as ``../internal_data_kit/sandbox_runner.py`` and the base runner at
``../../sandbox_runner.py``: the only kit-specific change is the ``tools=``
factory. The extra thing to remember for an API-backed kit is that the sandbox
needs the internal API credentials in its environment.

When you wire this into ``modal_sandbox_webhook.py``, add the two vars to the
sandbox ``env`` dict in ``_create_sandbox`` (read from the Modal Secret), e.g.::

    env={
        ...,
        "INTERNAL_API_BASE_URL": os.environ["INTERNAL_API_BASE_URL"],
        "INTERNAL_API_TOKEN": os.environ["INTERNAL_API_TOKEN"],
    }

so ``internal_api_tools._client()`` can build an authenticated client. The
token lives only in your Modal Secret and inside the sandbox; it never reaches
Anthropic.
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

from internal_api_tools import KIT_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="[runner] %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

WORKDIR = "/workspace"


def make_session_tools(ctx: AgentToolContext):
    """Per-session factory: built-in toolset bound to this session's context,
    plus this kit's API-backed tools. The custom tools reach the internal API
    via env-configured credentials, so they need no ``ctx``."""
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
