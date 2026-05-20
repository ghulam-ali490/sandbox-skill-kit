# Rollout plan: self-hosted CMA sandboxes for the workshop

This kit ships the building block for running Claude Managed Agents tool execution inside Modal sandboxes instead of Anthropic-managed sandboxes. Below is the order in which workshop kits should adopt it.

## When to adopt this kit

Adopt if at least one is true:

- Your kit's tools need to read or write data that should not leave your network (private DB, internal API, workshop-only file share).
- Your kit already deploys its own container, so running an `EnvironmentWorker` in that same image is cheaper than running a parallel Anthropic-side sandbox.
- You want one credential (`ANTHROPIC_ENVIRONMENT_KEY`) authorising the agent runner instead of long-lived org API keys reaching tool code.

Skip if your kit's tools are happy in Anthropic-managed sandboxes. The kit adds operational surface (Modal account, webhook registration, secret rotation) that only pays for itself when at least one of the above is true.

## Phased rollout

### Phase 1 — Prove the path (this kit)

Stand the kit up in a workshop-owned Modal account. Run the smoke test end-to-end against a throwaway CMA environment. Confirm:

- Webhook receives `session.status_run_started`
- Sandbox launches, runs `EnvironmentWorker.handle_item()`
- A trivial `bash ls /workspace` returns the expected output
- Sandbox auto-stops 60 seconds after `session.status_idle`

Estimated time: 1 day including Modal account setup.

### Phase 2 — Migrate one existing kit

Pick the smallest existing kit whose tools genuinely need internal data. Wrap that kit's tool functions into the `tools` callable passed to `worker(...)`. Deploy alongside the kit's existing infra. Run for a week, watching `modal app logs` and tool-call latency.

Estimated time: 2-3 days depending on tool complexity.

### Phase 3 — Update kit template

Once Phase 2 has run cleanly for a week, update the workshop's new-kit template so future kits inherit the sandbox pattern by default. Workshop docs get a "when to use self-hosted vs managed" section pointing at the rollout-criteria above.

### Phase 4 — MCP tunnels (deferred)

MCP tunnels are a separate Research Preview feature (cloudflared + Anthropic-operated edge). They expose private MCP servers to Claude without a public endpoint. Defer adoption until:

- The workshop has a concrete internal MCP server worth exposing
- Anthropic approves the workshop's tunnel access request (form at https://claude.com/form/claude-managed-agents)

Document the integration when both conditions are met.

## Open dependencies before Phase 2

- Modal workspace seat assigned to the workshop
- Anthropic CMA environment provisioned with both `environment_id` and `environment_key`
- One named owner for the Modal Secret rotation cadence (recommend rotate every 90 days)

## Cost notes

Modal Starter plan ($30/mo credits) covers Phase 1 and most of Phase 2. Sandbox pricing is per-second of container runtime: ~$0.00004/core/sec CPU. A typical agent session at 5 minutes of active tool execution costs well under a cent. Idle exit after 60s of `session.status_idle` keeps long-tail costs bounded.

If the workshop graduates beyond the Starter free credits, the next tier is Team ($250/mo) with 10 seats and $300 included credits. Re-evaluate at end of Phase 2.

## References

- Kit README (this repo): quickstart + file layout
- Anthropic cookbook (the original reference): https://github.com/anthropics/claude-cookbooks/tree/main/managed_agents/self_hosted_sandboxes
- SDK v0.103.0 release notes: https://github.com/anthropics/anthropic-sdk-python/releases/tag/v0.103.0
- Helpers doc, Self-Hosted Environment Runner section: https://github.com/anthropics/anthropic-sdk-python/blob/v0.103.0/helpers.md
- Modal sandbox guide: https://modal.com/docs/guide/sandbox
- MCP tunnels reference: https://platform.claude.com/docs/en/agents-and-tools/mcp-tunnels/reference
