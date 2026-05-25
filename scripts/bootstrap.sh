#!/usr/bin/env bash
# One-command bootstrap for sandbox-skill-kit.
#
# Reads ANTHROPIC_ENVIRONMENT_ID and ANTHROPIC_ENVIRONMENT_KEY from your
# shell environment, creates the Modal Secret with a placeholder webhook
# secret, deploys the webhook, and prints the *.modal.run URL you need to
# register in the Anthropic Console.
#
# After registering the URL, run this again with ANTHROPIC_WEBHOOK_SECRET
# set to the real `whsec_...` value to swap the placeholder for the real one.

set -euo pipefail

SECRET_NAME="cma-self-hosted-sandboxes-secrets"

require_env() {
  local name=$1
  if [ -z "${!name:-}" ]; then
    echo "ERROR: \$${name} is not set." >&2
    echo "Export it in your shell, then re-run:" >&2
    echo "  export ${name}='...'" >&2
    exit 1
  fi
}

require_env ANTHROPIC_ENVIRONMENT_ID
require_env ANTHROPIC_ENVIRONMENT_KEY

WEBHOOK_SECRET="${ANTHROPIC_WEBHOOK_SECRET:-placeholder}"

echo "==> Validating prerequisites (SDK + Modal auth; secret check is allowed to fail on first run)..."
# Run only the checks that should not yet need the Modal Secret -- the
# secret-exists check is allowed to fail here because we're about to create
# it. Other failures (SDK missing, modal CLI not authed) are real and must
# abort the bootstrap.
python - <<'PY' || { echo "ERROR: prerequisite check failed. Fix the issue above before re-running." >&2; exit 1; }
import sys
sys.path.insert(0, "scripts")
from validate import check_anthropic_sdk, check_modal_auth, check_env_key_shape
ok = check_anthropic_sdk() and check_modal_auth() and check_env_key_shape()
sys.exit(0 if ok else 1)
PY

echo "==> Creating / updating Modal Secret ${SECRET_NAME}..."
modal secret create "${SECRET_NAME}" \
  ANTHROPIC_WEBHOOK_SECRET="${WEBHOOK_SECRET}" \
  ANTHROPIC_ENVIRONMENT_ID="${ANTHROPIC_ENVIRONMENT_ID}" \
  ANTHROPIC_ENVIRONMENT_KEY="${ANTHROPIC_ENVIRONMENT_KEY}" \
  --force

echo "==> Deploying Modal app..."
modal deploy modal_sandbox_webhook.py

cat <<'EOF'

==================================================================
NEXT STEPS

1. Copy the *.modal.run URL printed above.
2. Register it as a webhook for `session.status_run_started` in the
   Anthropic Console.
3. Anthropic issues you a `whsec_...` secret. Re-run this script with
   that real secret in the environment:

     export ANTHROPIC_WEBHOOK_SECRET='whsec_...'
     ./scripts/bootstrap.sh

   This updates the Modal Secret in place. No redeploy needed; secrets
   are read at container start.
4. Run `python scripts/validate.py` to confirm everything green.
==================================================================
EOF
