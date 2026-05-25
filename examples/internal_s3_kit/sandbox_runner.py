"""Example sandbox runner for a kit backed by an internal OBJECT STORE.

Same shape as the other four examples; the only kit-specific change is the
``tools=`` factory. As with the API / DB / queue examples, the sandbox needs
the bucket connection info in its environment.

When you wire this into ``modal_sandbox_webhook.py``, add the vars to the
sandbox ``env`` dict in ``_create_sandbox`` (read from the Modal Secret),
e.g.::

    env={
        ...,
        "INTERNAL_S3_BUCKET":     os.environ["INTERNAL_S3_BUCKET"],
        "INTERNAL_S3_REGION":     os.environ["INTERNAL_S3_REGION"],
        "INTERNAL_S3_ACCESS_KEY": os.environ["INTERNAL_S3_ACCESS_KEY"],
        "INTERNAL_S3_SECRET_KEY": os.environ["INTERNAL_S3_SECRET_KEY"],
    }

so ``internal_s3_tools._bucket()`` (in a real kit) can construct an
authenticated client. The credentials live only in your Modal Secret and
inside the sandbox; they never reach Anthropic.

For a real backend (AWS S3 / GCS / R2 / MinIO), swap ``_bucket()`` in
``internal_s3_tools.py`` for an async client factory; the worker wiring
below is unchanged.
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

from internal_s3_tools import KIT_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="[runner] %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

WORKDIR = "/workspace"


def make_session_tools(ctx: AgentToolContext):
    """Per-session factory: built-in toolset bound to this session's context,
    plus this kit's object-store tools. The custom tools reach the bucket via
    env-configured credentials, so they need no ``ctx``."""
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
