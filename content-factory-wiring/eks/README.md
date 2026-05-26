# EKS Deployment

`contentx-postiz-webhook` + 5 CronJobs on EKS, namespace `content-factory`.

## Live state (as of last deploy)

```
cluster:    arn:aws:eks:us-east-1:970547373533:cluster/ai-cart-auto-cluster
namespace:  content-factory
image:      970547373533.dkr.ecr.us-east-1.amazonaws.com/contentx-postiz-webhook:sha-<git-hash>
ingress:    none yet — port-forward for now; uncomment 60-ingress.yaml when DNS is ready
secrets:    bootstrap Secret with random 64-hex values; swap to ExternalSecret (31-externalsecret.yaml) for prod
```

## Deploy flow

```bash
# One-shot deploy (idempotent, content-hashed image tag)
cd content-factory-wiring
APPLY=apply bash deploy/07_deploy_eks.sh

# Smoke test (4 probes, must all pass)
bash eks/smoke_test.sh k8s
```

The deploy script does:

1. Preflight check (kubectl, docker, aws)
2. Creates ECR repo if missing (`contentx-postiz-webhook`)
3. Computes a deterministic image tag from `sha256(services/ + tools/)` so re-runs are cache-hits
4. ECR login → buildx build (linux/amd64) → push
5. Materializes a fresh `CONTENTX_CERT_KEY` + `CONTENTX_WEBHOOK_SECRET` via `openssl rand`
6. `kubectl apply -f` all manifests in dependency order
7. Waits for deployment rollout

Run with `APPLY=dryrun` to validate manifests + push image WITHOUT applying.

## What's deployed

| Kind | Name | Purpose |
|---|---|---|
| Deployment | `contentx-postiz-webhook` | 2 replicas of the FastAPI service (HMAC-verified webhook for Postiz engagement) |
| Service | `contentx-postiz-webhook` | ClusterIP :80 → :8421 |
| ScaledObject (KEDA) | `contentx-postiz-webhook` | min 2, max 10 replicas; CPU-driven; ready for Prometheus when wired |
| PodDisruptionBudget | `contentx-postiz-webhook` | `minAvailable: 1` |
| NetworkPolicy | `contentx-postiz-webhook` | ingress from kube-system + same ns; egress to DNS + HTTPS, blocks 169.254.169.254 |
| ConfigMap | `contentx-webhook-config` | `LOG_LEVEL`, `CONTENTX_WORKING_DIR_ROOTS`, `CONTENTX_CHARACTER_REGISTRY` |
| Secret | `contentx-webhook-secrets` | `CONTENTX_CERT_KEY`, `CONTENTX_WEBHOOK_SECRET` |
| CronJob | `contentx-policy-reload`         | `*/5 * * * *` — refinery reload placeholder |
| CronJob | `contentx-engagement-reconciler` | `15,45 * * * *` — orphan post_id sweeper |
| CronJob | `contentx-engagement-scrape`     | `0 */6 * * *` — Postiz polling at 24/72/168h |
| CronJob | `contentx-hermes-indexer`        | `0 3 * * *` — nightly SessionDB reindex |
| CronJob | `contentx-persona-refresh`       | `30 4 * * *` — Honcho persona rebuild |
| ServiceAccount | `contentx-postiz-webhook` | runtime SA for the webhook |
| ServiceAccount | `contentx-cron` | runtime SA for the CronJobs |

## Smoke-test pass criteria

1. `GET /healthz` returns `{"ok": true, ...}`
2. `POST /engagement` with valid HMAC returns 2xx
3. `POST /engagement` with invalid HMAC returns **401**
4. `/metrics` shows `received_total ≥ 2` and `signature_invalid_total ≥ 1`

The included `smoke_test.sh k8s` runs all four through `kubectl port-forward`.

## Promotion to production (when ready)

1. **Add hostname** — edit `60-ingress.yaml`, replace `CERT_ARN_PLACEHOLDER` + `HOSTNAME_PLACEHOLDER`, uncomment, apply.
2. **Switch to ExternalSecret** — populate Infisical with `CONTENTX_CERT_KEY` and `CONTENTX_WEBHOOK_SECRET` under `/open-seo/`, then `kubectl apply -f 31-externalsecret.yaml`. The existing Secret will be re-created by ESO with the production values, no pod restart needed (envFrom will trigger rolling update on next deploy).
3. **Register webhook URL with Postiz** — `deploy/06_register_postiz_webhook.sh` with `CONTENTX_WEBHOOK_URL=https://<your-hostname>/engagement`.
4. **Watch for the first real engagement event** — `kubectl -n content-factory logs deploy/contentx-postiz-webhook --follow` should show `engagement post.engagement.24h for <run_id>` lines.

## Rollback

```bash
# Roll back to previous image
kubectl -n content-factory rollout undo deploy/contentx-postiz-webhook

# Full teardown (DESTRUCTIVE)
kubectl delete namespace content-factory
```

The namespace delete is destructive but safe — chain_of_custody for any received engagement was already mirrored to S3 (when that path is wired) and is independently retained per `policies/retention_policy.toml`.

## Known soft points

| Issue | Severity | Fix |
|---|---|---|
| KEDA `FailedGetResourceMetric` until metrics-server is installed | low | install metrics-server OR switch to Prometheus trigger |
| working_dir is `emptyDir` (ephemeral, per-pod) | medium | swap to PVC backed by EBS once a real working-dir lifecycle is in place |
| No ingress | low | covered above in promotion checklist |
| Bootstrap secret is `openssl rand -hex 32` per deploy → invalidates prior HMAC | medium | switch to ExternalSecret immediately for shared-secret stability |
