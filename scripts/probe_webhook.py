"""Probe a deployed sandbox-skill-kit webhook to verify it is alive without
needing Anthropic CMA access.

After ``modal deploy modal_sandbox_webhook.py``, the URL is live but there
is no way to know it actually works until a real CMA session fires (which
needs Anthropic Research Preview access). This script closes the Level 2
gap. It runs two checks:

  1. UNSIGNED PROBE: POST an empty body to the webhook with no signature
     headers. The handler must reject as 401. Proves the webhook is
     reachable and signature verification is enabled. Needs nothing
     beyond the URL.

  2. SIGNED PROBE: POST a correctly-signed body whose ``event.data.type``
     is anything OTHER than ``session.status_run_started``. The handler
     must accept (200 OK) and return ``{"status": "ignored", ...}``.
     Proves signature verification works end-to-end and the ignore branch
     is correctly wired -- the same code path a real ``run_started``
     event triggers, minus the actual sandbox spawn. Needs the
     ``whsec_...`` secret.

The signed probe is skipped (with a friendly note) if the webhook secret
is not provided; the unsigned probe alone is still a useful deploy
heartbeat.

Usage:
    export ANTHROPIC_WEBHOOK_URL='https://<workspace>--<app>-webhook.modal.run'
    export ANTHROPIC_WEBHOOK_SECRET='whsec_...'       # optional; enables signed probe
    python scripts/probe_webhook.py

    # or explicit args
    python scripts/probe_webhook.py --url URL --whsec whsec_...

Exit code: 0 if all attempted probes pass; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

# Event type to use for the signed probe. Anything other than
# session.status_run_started exercises the ignore branch of the handler.
PROBE_EVENT_TYPE = "session.status_idle"


@dataclass(frozen=True)
class ProbeResult:
    name: str
    passed: bool
    detail: str


def _post(url: str, *, body: bytes, headers: dict[str, str], timeout: float = 15.0):
    """Wrapper around httpx.post -- factored out so tests can monkeypatch."""
    return httpx.post(url, content=body, headers=headers, timeout=timeout)


def unsigned_probe(url: str) -> ProbeResult:
    """POST an empty body with no signature headers. Expect 401."""
    try:
        resp = _post(url, body=b"", headers={"content-type": "application/json"})
    except httpx.HTTPError as e:
        return ProbeResult(
            "unsigned probe",
            False,
            f"network error ({type(e).__name__}: {e}). Is the URL correct?",
        )
    if resp.status_code == 401:
        return ProbeResult(
            "unsigned probe",
            True,
            "got 401 (signature verification correctly rejected empty body)",
        )
    return ProbeResult(
        "unsigned probe",
        False,
        f"expected 401, got {resp.status_code}. Body: {resp.text[:200]!r}",
    )


def _build_signed_headers(
    whsecret: str, *, body: bytes, msg_id: str, timestamp: datetime
) -> dict[str, str]:
    """Build the Standard Webhooks headers Anthropic expects."""
    # standardwebhooks is already in the kit's deps via anthropic[webhooks].
    from standardwebhooks import Webhook

    signer = Webhook(whsecret)
    signature = signer.sign(msg_id=msg_id, timestamp=timestamp, data=body.decode())
    return {
        "content-type": "application/json",
        "webhook-id": msg_id,
        "webhook-timestamp": str(int(timestamp.timestamp())),
        "webhook-signature": signature,
    }


def signed_probe(url: str, whsecret: str) -> ProbeResult:
    """POST a correctly-signed non-run_started event. Expect 200 + ignored."""
    msg_id = f"msg_probe_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.now(tz=UTC)
    payload = {
        "id": f"evt_probe_{uuid.uuid4().hex[:12]}",
        "type": PROBE_EVENT_TYPE,
        "data": {"type": PROBE_EVENT_TYPE, "id": "sess_probe_ignored"},
    }
    body = json.dumps(payload).encode()
    try:
        headers = _build_signed_headers(
            whsecret, body=body, msg_id=msg_id, timestamp=timestamp
        )
    except Exception as e:
        return ProbeResult(
            "signed probe",
            False,
            f"failed to sign payload ({type(e).__name__}: {e}). "
            "Is the whsec_ secret correctly formed?",
        )
    try:
        resp = _post(url, body=body, headers=headers)
    except httpx.HTTPError as e:
        return ProbeResult(
            "signed probe",
            False,
            f"network error ({type(e).__name__}: {e}).",
        )
    if resp.status_code != 200:
        snippet = resp.text[:200]
        return ProbeResult(
            "signed probe",
            False,
            f"expected 200, got {resp.status_code}. Body: {snippet!r}. "
            "Common causes: webhook secret mismatch between your local env "
            "and the Modal Secret; or the deployed event-routing was changed.",
        )
    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError):
        return ProbeResult(
            "signed probe", False, f"response not JSON: {resp.text[:200]!r}"
        )
    if data.get("status") != "ignored":
        return ProbeResult(
            "signed probe",
            False,
            f"expected status=ignored, got {data!r}. The signature verified "
            "but the handler did not take the ignore branch -- maybe the "
            "event type changed?",
        )
    if data.get("event_type") != PROBE_EVENT_TYPE:
        return ProbeResult(
            "signed probe",
            False,
            f"event_type echoed back as {data.get('event_type')!r}, "
            f"expected {PROBE_EVENT_TYPE!r}.",
        )
    return ProbeResult(
        "signed probe",
        True,
        "got 200 + status=ignored (signature verified; ignore branch correct)",
    )


def run_probes(url: str, whsecret: str | None) -> int:
    """Run all probes that have their prerequisites. Return overall exit code."""
    results: list[ProbeResult] = [unsigned_probe(url)]
    if whsecret:
        results.append(signed_probe(url, whsecret))
    else:
        print(
            "  SKIP  signed probe (ANTHROPIC_WEBHOOK_SECRET not provided; "
            "unsigned heartbeat only)"
        )

    overall = 0
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  {status}  {r.name}: {r.detail}")
        if not r.passed:
            overall = 1
    if overall == 0:
        print("\nAll probes passed. The webhook is live and verifying signatures.")
    else:
        print(
            "\nOne or more probes failed. Check `modal app logs cma-self-hosted-sandboxes` "
            "for the matching incoming request."
        )
    return overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a deployed sandbox-skill-kit webhook is alive + "
        "verifying signatures, without needing CMA access.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("ANTHROPIC_WEBHOOK_URL"),
        help="Deployed webhook URL (or set ANTHROPIC_WEBHOOK_URL).",
    )
    parser.add_argument(
        "--whsec",
        default=os.environ.get("ANTHROPIC_WEBHOOK_SECRET"),
        help="Webhook secret 'whsec_...' (or set ANTHROPIC_WEBHOOK_SECRET); "
        "omit to run only the unsigned probe.",
    )
    args = parser.parse_args(argv)

    if not args.url:
        print(
            "ERROR: --url not given and ANTHROPIC_WEBHOOK_URL not set. "
            "Provide the deployed *.modal.run URL.",
            file=sys.stderr,
        )
        return 2

    print(f"Probing {args.url}:")
    return run_probes(args.url, args.whsec)


if __name__ == "__main__":
    sys.exit(main())
