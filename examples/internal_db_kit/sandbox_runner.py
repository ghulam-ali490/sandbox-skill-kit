"""Example sandbox runner for a kit backed by an internal DATABASE.

Same shape as ``../internal_data_kit/sandbox_runner.py`` and the API example
``../internal_api_kit/sandbox_runner.py``: the only kit-specific change is the
``tools=`` factory. As with the API example, the sandbox needs the DB
connection info in its environment.

When you wire this into ``modal_sandbox_webhook.py``, add the DSN var to the
sandbox ``env`` dict in ``_create_sandbox`` (read from the Modal Secret), e.g.::

    env={
        ...,
        "INTERNAL_DB_PATH": os.environ["INTERNAL_DB_PATH"],
    }

so ``internal_db_tools._conn()`` can open the connection. The DSN lives only
in your Modal Secret and inside the sandbox; it never reaches Anthropic.

For non-sqlite databases, swap ``_conn()`` in ``internal_db_tools.py`` for an
async driver (``asyncpg``, ``aiomysql``, ...) and rename the env var
accordingly; the worker wiring below is unchanged.
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

from internal_db_tools import KIT_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="[runner] %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

WORKDIR = "/workspace"


def make_session_tools(ctx: AgentToolContext):
    """Per-session factory: built-in toolset bound to this session's context,
    plus this kit's DB-backed tools. The custom tools reach the DB via the
    env-configured DSN, so they need no ``ctx``."""
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
