# Example: migrating a kit onto self-hosted sandboxes

This is a worked **Phase 2** reference (see `../../docs/rollout.md`). It shows
what a workshop kit looks like *after* it adopts sandbox-skill-kit so its tools
run inside your Modal account instead of an Anthropic-managed sandbox.

There is no real kit to migrate yet -- the existing kits (`goal-command-kit`,
`skill-recommender-kit`) are documentation-only and have no tools. So this
example stands in as the copy-paste pattern for the first kit that *does* ship
tools needing internal data.

## The scenario

A kit whose agent must answer questions about **internal warehouse data** -- order
status and stock levels -- that should never leave the network. The data here is
a bundled JSON file (`internal_data.json`); in a real kit it would be a private
DB query or an internal API call.

## The whole migration in one diff

The base runner (`../../sandbox_runner.py`) lets the worker use its default
toolset. The migration adds **one argument** -- a `tools=` factory:

```python
from anthropic.lib.tools.agent_toolset import AgentToolContext, beta_agent_toolset_20260401
from internal_tools import KIT_TOOLS

def make_session_tools(ctx: AgentToolContext):
    # default toolset (bash/read/write/edit/glob/grep) + this kit's tools
    return [*beta_agent_toolset_20260401(ctx), *KIT_TOOLS]

worker(environment_key=..., tools=make_session_tools, workdir="/workspace", ...)
```

That is the entire Phase 2 change. Everything else (auth via the single
`ANTHROPIC_ENVIRONMENT_KEY`, workdir, 60s idle policy) is unchanged.

## Defining a tool

A tool is a plain async function with the `beta_async_tool` decorator. The JSON
input schema is inferred from the type hints and the docstring `Args` section:

```python
from anthropic.lib.tools import beta_async_tool

@beta_async_tool
async def lookup_order_status(order_id: str) -> str:
    """Look up the shipping status of an internal order.

    Args:
        order_id: Internal order id, e.g. "ORD-1001".
    """
    ...  # reach your internal data here; runs inside YOUR sandbox
```

See `internal_tools.py` for the two tools used here.

## Files

- `internal_tools.py` -- the kit's two custom tools + a `KIT_TOOLS` export
- `internal_data.json` -- stand-in for private data the tools read
- `sandbox_runner.py` -- the migrated runner; identical to the base one except for `tools=`
- `verify.py` -- Level-1 check (no CMA/Modal needed): names, schemas, factory output, live tool calls

## Verify it (no account needed)

```shell
cd examples/internal_data_kit
python verify.py
```

Expected tail: `PASS: migration wiring is correct.` It confirms the factory
returns the 6 default tools plus the 2 custom tools, and that the custom tools
return data from the bundled file.

## Going live (needs CMA access)

To run this against a real session you need the same things the kit's top-level
README step 6 lists: a CMA environment, the webhook registered, and the Modal
secret populated. Bundle `internal_tools.py` + `internal_data.json` into the
sandbox image in `modal_sandbox_webhook.py`, point the sandbox entrypoint at
this `sandbox_runner.py`, then drive a session that asks e.g. "what's the status
of order ORD-1001?" -- the agent will call `lookup_order_status` inside your
sandbox.
