# Security model

This kit runs Claude Managed Agents (CMA) tool execution inside Modal
sandboxes on **your** infrastructure. This document states what that isolation
does and does not give you, and how secrets are handled, so adopters can make
an informed call. It is not a guarantee; review it against your own threat
model before putting sensitive data behind it.

## What the kit protects

- **Tool execution stays on your infra.** `bash` / `read` / `write` / `edit` /
  `glob` / `grep` run inside a Modal Sandbox you own, not in an
  Anthropic-managed sandbox. Data the tools touch (a private DB, an internal
  API, a workshop-only file share) does not have to leave your network for the
  tools to work.
- **One scoped credential reaches tool code.** The runner authenticates with a
  single `ANTHROPIC_ENVIRONMENT_KEY` (an `sk-ant-oat-` environment key), not a
  long-lived org API key. The org API key is used only by the operator-run
  `scripts/e2e_test.py` for session setup, and never ships into the sandbox.
- **Per-session isolation.** Each CMA session gets its own Modal Sandbox and its
  own `cma-session-<id>` volume. One session's working tree is not visible to
  another.
- **Webhook authenticity.** Every delivery is verified with the Standard
  Webhooks signature (`client.beta.webhooks.unwrap()`); a bad or missing
  signature is rejected with HTTP 401 before any work is drained. The reject
  path logs only the exception *type*, never the request body.
- **Bounded lifetime.** Sandboxes auto-stop ~60s after `session.status_idle`
  and carry a hard `timeout`, so a hung or abandoned session cannot run
  indefinitely.

## What the kit does NOT protect against

- **The model's reasoning still runs on Anthropic.** Only tool *execution* is
  local. Prompt content, tool *inputs*, and tool *outputs* are exchanged with
  the Anthropic API. Do not assume data is "air-gapped" just because the tool
  ran locally; if a tool returns secret data, that data goes back to the model.
- **The agent has a real shell.** Inside the sandbox the agent can run arbitrary
  `bash`. Isolation is at the **sandbox boundary** (Modal container + volume),
  not within it. Anything the sandbox's network and mounted volumes can reach,
  the agent can reach. Scope the sandbox's egress and mounts to the minimum the
  kit's tools actually need.
- **Not a multi-tenant trust boundary by itself.** Per-session volumes separate
  sessions, but all sessions for one environment share the same environment key
  and Modal workspace. Treat the environment key as able to act for any session
  in that environment.
- **No data-loss protection for what you mount.** If you mount a writable path
  with real data, the agent can modify or delete it. Mount read-only, or mount
  copies, when the source is precious.

## Secret handling

- The three secrets (`ANTHROPIC_WEBHOOK_SECRET`, `ANTHROPIC_ENVIRONMENT_ID`,
  `ANTHROPIC_ENVIRONMENT_KEY`) live **only** in a Modal Secret
  (`cma-self-hosted-sandboxes-secrets`), read at container start. They are not
  committed and not baked into the image.
- `.env.example` ships placeholder names only. `setup_secret.ps1` (the local
  Windows helper that calls `modal secret create`) is gitignored and must stay
  untracked, so real keys never enter git history.
- `scripts/validate.py` checks the environment key *shape* (`sk-ant-oat-`
  prefix) only when the key happens to be in the local env; it never reads the
  live value back out of the Modal Secret.
- **Rotation:** rotate the environment key and webhook secret on a schedule
  (the rollout doc recommends every 90 days, with one named owner). Re-create
  the Modal Secret with `--force`; no redeploy is needed.

## Reporting an issue

This is a workshop R&D kit, not a production service. If you find a security
problem in the kit's own code, open an issue on the repository describing the
impact and a reproduction. Do not include real credentials or customer data in
the report. For issues in the upstream Anthropic SDK or cookbook, report them
to the respective upstream project.
