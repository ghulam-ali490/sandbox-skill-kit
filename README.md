# sandbox-skill-kit

Workshop R&D kit. Spin up a self-hosted sandbox for Claude Managed Agents on Modal in three commands. Uses `anthropic-sdk-python` v0.103.1 sandbox helpers (released 2026-05-19).

## What this gives you

A Modal-deployed webhook that:

1. Receives a `session.status_run_started` event from Anthropic
2. Drains the environment work queue (recovers any missed deliveries in one pass)
3. Spins up a Modal Sandbox per session that runs `client.beta.environments.work.worker(...).handle_item()`
4. Streams `bash` / `read` / `write` / `edit` / `glob` / `grep` tool calls into the sandbox, returns results to the agent
5. Auto-exits 60 seconds after `session.status_idle`

The kit isolates agent tool execution to **your infrastructure** (Modal) instead of Anthropic-managed sandboxes. Useful when tools need to see internal data, files, or services that should not leave your network.

## When to use it

- You are running a workshop kit whose tools need internal data (a private DB, a workshop-only file share, an internal API)
- You want one credential (`ANTHROPIC_ENVIRONMENT_KEY`) authorising the agent runner instead of long-lived org API keys
- You are comfortable owning a Modal account for the sandbox

If your kit's tools are happy in Anthropic-managed sandboxes, you do not need this.

## Quickstart

### 1. Prerequisites

- Python 3.12+
- A Modal account (https://modal.com, free Starter plan is enough for R&D)
- An Anthropic Claude Managed Agents environment with environment ID + environment key

### 2. Install and authenticate Modal

```shell
pip install -r requirements.txt
modal setup    # one-time browser auth to your Modal workspace
```

### 3. Set Modal secrets

```shell
modal secret create cma-self-hosted-sandboxes-secrets \
    ANTHROPIC_WEBHOOK_SECRET=placeholder \
    ANTHROPIC_ENVIRONMENT_ID='env_...' \
    ANTHROPIC_ENVIRONMENT_KEY='sk-ant-oat...'
```

(Use a placeholder webhook secret for now; you swap it for the real one after the first deploy.)

### 4. Deploy

```shell
modal deploy modal_sandbox_webhook.py
```

Modal prints a `*.modal.run` URL. Register that URL as a webhook for `session.status_run_started` in the Anthropic Console (or via the API). Anthropic gives you back a `whsec_...` secret. Plug it in:

```shell
modal secret create cma-self-hosted-sandboxes-secrets \
    ANTHROPIC_WEBHOOK_SECRET='whsec_...' \
    ANTHROPIC_ENVIRONMENT_ID='env_...' \
    ANTHROPIC_ENVIRONMENT_KEY='sk-ant-oat...' \
    --force
```

No redeploy needed; secrets are read at container start.

### 5. Smoke-test

```shell
python scripts/validate.py
```

This walks through every prereq: Modal authed, secret exists, SDK version correct, environment key format matches `sk-ant-oat-`, etc. Catches the usual day-1 misconfiguration before you fire a real session.

### 6. Run a real session (Level 3 end-to-end test)

The kit ships a driver that creates a session, sends a task that forces a real
shell command inside your Modal sandbox, polls to completion, prints the
transcript, and exits non-zero on failure:

```shell
export ANTHROPIC_API_KEY=sk-ant-api...        # org key, used for session setup only
export ANTHROPIC_ENVIRONMENT_ID=env_...       # SAME env_... that is in the Modal Secret
export CMA_AGENT_ID=agt_...                    # optional; omit to auto-create a test agent
python scripts/e2e_test.py
```

In another terminal, watch the sandbox side:

```shell
modal app logs cma-self-hosted-sandboxes
```

You should see `[webhook] acked work=... session=... sandbox=sb-...` and then
`[runner] ...` lines from the sandbox itself, and the driver should end with
`PASS: agent executed tools inside the self-hosted Modal sandbox`.

Under the hood the driver does the equivalent of:

```py
import anthropic
client = anthropic.Anthropic()  # uses your org API key for THIS step only
session = client.beta.sessions.create(agent=AGENT_ID, environment_id=ENVIRONMENT_ID)
client.beta.sessions.events.send(
    session.id,
    # content is an array of content blocks, not a bare string
    events=[{"type": "user.message", "content": [{"type": "text", "text": "run `uname -a`"}]}],
)
```

## Files

- `modal_sandbox_webhook.py` — Modal app + webhook receiver + work-queue drainer + sandbox launcher
- `sandbox_runner.py` — runs inside each Modal Sandbox; one call to `EnvironmentWorker.handle_item()`
- `requirements.txt` — `anthropic[webhooks]>=0.103.1`, `modal>=0.60`, `fastapi[standard]`, `standardwebhooks`
- `.env.example` — placeholder names for local secret setup; the real values live in Modal Secrets
- `scripts/bootstrap.sh` — one-command wrapper around `modal secret create` + `modal deploy`
- `scripts/validate.py` — pre-flight sanity check (Modal authed, secret exists, SDK version, env key shape)
- `scripts/e2e_test.py` — Level 3 driver: fires a real session and asserts tools ran inside the Modal sandbox
- `docs/rollout.md` — when to use this kit vs Anthropic-managed sandboxes, plus a workshop-wide rollout plan

## How it differs from the Anthropic cookbook

The code in `modal_sandbox_webhook.py` and `sandbox_runner.py` is adapted from `anthropics/claude-cookbooks/managed_agents/self_hosted_sandboxes/modal/` (MIT). The kit adds:

- One-command `scripts/bootstrap.sh` so a fresh workshop kit gets to "deployed" in under five minutes
- `scripts/validate.py` pre-flight check
- `docs/rollout.md` workshop-specific guidance
- Pinned dependency versions known good with v0.103.1

If you want the unwrapped cookbook reference, https://github.com/anthropics/claude-cookbooks/tree/main/managed_agents/self_hosted_sandboxes is the source.

## License

MIT (matches the upstream cookbook).
