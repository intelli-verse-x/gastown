"""Postiz engagement webhook → bead update bridge.

Receives signed webhooks from Postiz, verifies the HMAC, maps post_id back to
the originating content-factory run_id via Hermes SessionDB, and updates the
matching `engagement_*` bead (or creates one).

Run:
    CONTENTX_WEBHOOK_SECRET=$(vault kv get -field=value contentx/postiz-webhook-secret) \
    CONTENTX_CERT_KEY=$(vault kv get -field=value contentx/cert-key) \
    uvicorn services.postiz_webhook.server:app --host 0.0.0.0 --port 8421

Endpoints:
    GET  /healthz                  — liveness + version
    POST /engagement               — Postiz webhook target
    GET  /metrics                  — Prometheus-text counters

Signing:
    Postiz sends a header `X-Postiz-Signature: sha256=<hex>` over the raw body.
    We verify with hmac.compare_digest. Missing or invalid signature → 401.

Side effects per request:
    1. Append a HMAC-signed entry to the matching run's chain_of_custody.jsonl
    2. Update the engagement bead (create on first call)
    3. Increment Prometheus counters
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "studio_gates"))

# Reuse the studio-gate signing primitives
from __init__ import sign as gate_sign, now_utc  # type: ignore  # noqa: E402
from g14_chain_of_custody import append as coc_append  # type: ignore  # noqa: E402

log = logging.getLogger("postiz-webhook")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

app = FastAPI(title="contentx-postiz-webhook", version="1.0.0")

# ---------------------------------------------------------------------------
# Counters (Prometheus text format)
# ---------------------------------------------------------------------------
COUNTERS: dict[str, int] = {
    "postiz_webhook_received_total": 0,
    "postiz_webhook_signature_invalid_total": 0,
    "postiz_webhook_no_run_id_mapping_total": 0,
    "postiz_webhook_bead_updated_total": 0,
    "postiz_webhook_bead_created_total": 0,
    "postiz_webhook_errors_total": 0,
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _secret() -> bytes:
    s = os.environ.get("CONTENTX_WEBHOOK_SECRET", "")
    if not s:
        raise RuntimeError("CONTENTX_WEBHOOK_SECRET not set")
    return s.encode()


WORKING_DIR_ROOTS = [
    Path(p) for p in os.environ.get(
        "CONTENTX_WORKING_DIR_ROOTS",
        "/var/lib/contentx/working_dir:/Users/devashishbadlani/dev/content-factory/.working_dir",
    ).split(":") if p.strip()
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, header_value: str) -> bool:
    if not header_value.startswith("sha256="):
        return False
    expected = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    got = header_value.split("=", 1)[1].strip()
    return hmac.compare_digest(expected, got)


def _find_run_path(post_id: str, run_id_hint: str | None = None) -> Path | None:
    """Find the working_dir/<run_id>/ folder this post belongs to.

    Strategy:
      1. If run_id_hint provided, look it up directly
      2. Search publish_metadata.json files under WORKING_DIR_ROOTS for matching post_id
    """
    if run_id_hint:
        for root in WORKING_DIR_ROOTS:
            for candidate in root.rglob(run_id_hint):
                if candidate.is_dir():
                    return candidate
    for root in WORKING_DIR_ROOTS:
        if not root.exists(): continue
        for pm in root.rglob("publish_metadata.json"):
            try:
                data = json.loads(pm.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("postiz_post_id") == post_id or data.get("post_id") == post_id:
                # Walk up to find the run_id directory (one with checkpoint.json)
                p = pm.parent
                while p != p.parent:
                    if (p / "checkpoint.json").exists() or (p / "run.json").exists():
                        return p
                    p = p.parent
    return None


def _normalize_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """Postiz field names vary; coerce to canonical schema."""
    src = payload.get("metrics") or payload.get("engagement") or payload
    return {
        "views":           int(src.get("views") or src.get("impressions") or 0),
        "likes":           int(src.get("likes") or 0),
        "comments":        int(src.get("comments") or 0),
        "shares":          int(src.get("shares") or src.get("reposts") or 0),
        "saves":           int(src.get("saves") or src.get("bookmarks") or 0),
        "retention_avg":   float(src.get("retention_avg") or src.get("avg_watch_pct") or 0.0),
        "retention_30s":   float(src.get("retention_30s") or 0.0),
        "ctr":             float(src.get("ctr") or 0.0),
        "platform":        payload.get("platform") or src.get("platform") or "unknown",
        "post_id":         payload.get("post_id") or src.get("post_id") or "",
        "checkpoint":      payload.get("event") or "engagement.update",
        "received_at":     now_utc(),
    }


def _update_bead(run_path: Path, post_id: str, metrics: dict[str, Any]) -> tuple[bool, str]:
    """Update or create the engagement bead. Returns (created, bead_id)."""
    bead_pointer = run_path / "engagement_bead.txt"
    if bead_pointer.exists():
        bead_id = bead_pointer.read_text().strip()
        try:
            subprocess.run(
                ["bd", "update", bead_id, "--state", "in_progress",
                 "--comment", json.dumps(metrics)],
                capture_output=True, text=True, timeout=15,
            )
            COUNTERS["postiz_webhook_bead_updated_total"] += 1
            return False, bead_id
        except Exception as exc:
            log.warning(f"bd update failed: {exc}; will fall back to JSON-only update")
            return False, bead_id

    # First touch — create the bead
    try:
        r = subprocess.run(
            ["bd", "create",
             "--title", f"engagement: {run_path.name} ({metrics['platform']})",
             "--type", "task",
             "--priority", "2",
             "--label", "engagement",
             "--label", f"platform:{metrics['platform']}",
             "--label", f"post:{post_id}"],
            capture_output=True, text=True, timeout=15,
        )
        # Extract bead id from output like "Created bd-xyz123" or "abc-xyz123"
        import re
        m = re.search(r"\b([A-Za-z0-9-]+-[a-z0-9]+)\b", r.stdout)
        if m:
            bead_id = m.group(1)
            bead_pointer.write_text(bead_id)
            COUNTERS["postiz_webhook_bead_created_total"] += 1
            return True, bead_id
    except Exception as exc:
        log.warning(f"bd create failed: {exc}; engagement saved to disk only")

    # No bd CLI — fall back to a local JSON record
    return False, ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "service": "contentx-postiz-webhook",
        "version": "1.0.0",
        "now": now_utc(),
        "secret_loaded": bool(os.environ.get("CONTENTX_WEBHOOK_SECRET")),
        "cert_key_loaded": bool(os.environ.get("CONTENTX_CERT_KEY")),
        "working_dir_roots": [str(p) for p in WORKING_DIR_ROOTS],
    }


@app.get("/metrics")
def metrics():
    lines = []
    for k, v in COUNTERS.items():
        lines.append(f"# TYPE {k} counter")
        lines.append(f"{k} {v}")
    return PlainTextResponse("\n".join(lines) + "\n")


@app.post("/engagement")
async def engagement(request: Request):
    COUNTERS["postiz_webhook_received_total"] += 1
    body = await request.body()
    sig_header = request.headers.get("x-postiz-signature", "")
    if not _verify_signature(body, sig_header):
        COUNTERS["postiz_webhook_signature_invalid_total"] += 1
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        COUNTERS["postiz_webhook_errors_total"] += 1
        raise HTTPException(status_code=400, detail=f"invalid json: {e}")

    post_id = payload.get("post_id") or (payload.get("metrics") or {}).get("post_id") or ""
    run_id_hint = payload.get("run_id") or payload.get("contentx_run_id")
    if not post_id:
        COUNTERS["postiz_webhook_errors_total"] += 1
        raise HTTPException(status_code=400, detail="missing post_id")

    run_path = _find_run_path(post_id, run_id_hint)
    if not run_path:
        COUNTERS["postiz_webhook_no_run_id_mapping_total"] += 1
        log.warning(f"no run_id mapping for post {post_id}; dropping")
        return JSONResponse(
            status_code=202,
            content={"status": "accepted_no_mapping", "post_id": post_id},
        )

    metrics_canonical = _normalize_metrics(payload)

    # Write into the run's liveops/ folder
    liveops = run_path / "liveops"
    liveops.mkdir(exist_ok=True)
    event_name = metrics_canonical["checkpoint"].replace(".", "_")
    out = liveops / f"{event_name}_{int(time.time())}.json"
    out.write_text(json.dumps(metrics_canonical, indent=2))

    # Append to chain of custody — every engagement update is auditable
    try:
        coc_append(run_path, {
            "kind": "engagement_update",
            "post_id": post_id,
            "platform": metrics_canonical["platform"],
            "checkpoint": metrics_canonical["checkpoint"],
            "metrics_hash": hashlib.sha256(
                json.dumps(metrics_canonical, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        })
    except Exception as exc:
        log.warning(f"chain_of_custody append failed: {exc}")

    created, bead_id = _update_bead(run_path, post_id, metrics_canonical)

    response = {
        "status": "ok",
        "run_id": run_path.name,
        "bead_id": bead_id,
        "bead_created": created,
        "metrics": metrics_canonical,
    }
    log.info(f"engagement {metrics_canonical['checkpoint']} for {run_path.name} ({post_id})")
    return response
