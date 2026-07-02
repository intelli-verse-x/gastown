# services/postiz_webhook

FastAPI service that receives Postiz engagement webhooks and pushes them into
content-factory's run feedback loop. Closes G12 (live-ops).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/healthz`     | liveness + config sanity |
| GET  | `/metrics`     | Prometheus counters |
| POST | `/engagement`  | Postiz webhook target (HMAC-verified) |

## Per-request side effects

For every `POST /engagement`:

1. Verify `X-Postiz-Signature` HMAC against `CONTENTX_WEBHOOK_SECRET`.
2. Resolve `post_id` → `run_path` via `publish_metadata.json` scan.
3. Normalize the metrics into `views, likes, comments, shares, saves, retention_avg, retention_30s, ctr`.
4. Write `liveops/<checkpoint>_<ts>.json` inside the run folder.
5. Append a signed entry to `chain_of_custody.jsonl` (uses the same HMAC primitive as the studio gates).
6. `bd create` (first touch) or `bd update` the engagement bead — Hermes' planner reads this on tomorrow's slate.

## Local dev

```bash
export CONTENTX_WEBHOOK_SECRET=$(openssl rand -hex 32)
export CONTENTX_CERT_KEY=$(openssl rand -hex 32)
export CONTENTX_WORKING_DIR_ROOTS=$HOME/dev/content-factory/.working_dir
pip install -r requirements.txt
uvicorn services.postiz_webhook.server:app --reload --port 8421
```

Smoke test:

```bash
BODY='{"post_id":"abc123","event":"post.engagement.24h","platform":"youtube_shorts","metrics":{"views":12000,"likes":410,"comments":52,"shares":17,"retention_30s":0.62}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$CONTENTX_WEBHOOK_SECRET" | awk '{print $2}')"
curl -fsS -X POST http://localhost:8421/engagement \
  -H "X-Postiz-Signature: $SIG" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

## Production

- Behind nginx or ALB with TLS termination
- Vault-injected `CONTENTX_WEBHOOK_SECRET` via systemd `EnvironmentFile=/etc/contentx/webhook.env`
- systemd unit ships as `postiz-webhook.service`
- Docker image build: `docker build -f services/postiz_webhook/Dockerfile -t contentx-postiz-webhook .`

## Failure modes & metrics

| Counter | What it means |
|---|---|
| `postiz_webhook_received_total` | total requests handled |
| `postiz_webhook_signature_invalid_total` | HMAC mismatch (attacker, drift, or rotated secret) |
| `postiz_webhook_no_run_id_mapping_total` | post_id couldn't be matched to a run; payload preserved in nginx logs |
| `postiz_webhook_bead_created_total` | first engagement event for that run |
| `postiz_webhook_bead_updated_total` | follow-up engagement event |
| `postiz_webhook_errors_total` | 4xx/5xx returned |

Alarm if `signature_invalid_total / received_total > 0.01` (more than 1% bad signatures).
