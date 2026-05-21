"""Example sandbox runner AFTER a kit adopts sandbox-skill-kit.

Compare this with the base runner at ``../../sandbox_runner.py``. The ONLY
difference is the ``tools=`` argument: instead of letting the worker use its
default toolset, this kit passes a per-session factory that returns the default
toolset PLUS the kit's own internal-data tools. Auth, workdir, and idle policy
are unchanged.

That single change is the whole Phase 2 migration: keep the worker, swap in a
``tools`` factory built from ``beta_agent_toolset_20260401(ctx)`` extended with
your tool objects.
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

from internal_tools import KIT_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="[runner] %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

WORKDIR = "/workspace"


def make_session_tools(ctx: AgentToolContext):
    """Per-session tool factory.

    ``worker(tools=...)`` calls this once per claimed session with that
    session's ``AgentToolContext``. We return the built-in toolset (bash, read,
    write, edit, glob, grep) bound to that context, plus this kit's tools. The
    custom tools need no context here because they reach internal data directly;
    a tool that needed the session workdir could close over ``ctx`` instead.
    """
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
