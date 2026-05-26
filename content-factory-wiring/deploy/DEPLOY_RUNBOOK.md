# Deploy Runbook — Content-Factory Studio Gates

**Audience:** Ops engineer with `vault`, `aws`, `gt`, `hermes`, and `ssh` access.
**Duration:** 45 minutes solo, 25 minutes with two people in parallel.
**Result:** Studio gates enforcing every `content-factory` publish, with chain-of-custody to S3 and engagement loop closed via Postiz.

---

## Pre-flight (one-time, ~5 min)

```bash
# Sanity — the local bundle is verified
cd content-factory-wiring/
CONTENTX_CERT_KEY=test-key python tools/studio_gates/post_deploy_verify.py   # → 12/12
CONTENTX_CERT_KEY=test-key python tools/validate_bundle.py                   # → 28/28
```

If either fails, **DO NOT PROCEED.** Open a bd issue and fix the bundle first.

---

## Step 1 · Vault (5 min, Person A)

```bash
export VAULT_ADDR=https://vault.contentx.internal
export VAULT_TOKEN=$(vault login -method=oidc -format=json | jq -r .auth.client_token)
bash deploy/01_provision_vault.sh
```

**Verify:**

```bash
vault kv get -field=value contentx/cert-key | wc -c   # → 65 (64 hex + newline)
```

**Decision:** confirm with Security the rotation schedule is on calendar (monthly).

---

## Step 2 · S3 audit-cold bucket (15 min, Person B)

```bash
export AWS_REGION=us-east-1
export BUCKET=contentx-audit-cold
bash deploy/05_setup_s3_audit_cold.sh
```

**Verify:**

```bash
aws s3api get-bucket-lifecycle-configuration --bucket $BUCKET | jq .
aws s3api get-bucket-versioning --bucket $BUCKET    # Status: Enabled
```

**Decision (Legal):** confirm 7y default. EU/DE may require 10y for financial-services content. If so, edit `RETENTION_DAYS` and re-run.

---

## Step 3 · First Gas Town host (20 min, Person A)

```bash
ssh contentx-rig-1
git clone <repo>; cd content-factory-wiring

# Bootstrap (installs go, bd, ICU, ffmpeg, python deps)
bash deploy/02_bootstrap_host.sh

# Load vault key into the shell that will run gt / hermes
export CONTENTX_CERT_KEY=$(vault kv get -field=value contentx/cert-key)

# Verify before touching refinery
python tools/studio_gates/post_deploy_verify.py     # MUST be 12/12

# Load refinery + witness + convoys
bash deploy/03_deploy_refinery.sh
bash deploy/04_import_hermes_cron.sh
```

**Verify:**

```bash
gt refinery list-gates | grep -c 'studio_gate' # → 14
hermes cron list | grep engagement              # → 4 jobs
```

---

## Step 4 · Postiz webhook (15 min, Person B)

### 4a · Deploy the webhook receiver

```bash
ssh contentx-rig-1
cd content-factory-wiring/services/postiz_webhook
sudo cp postiz-webhook.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now postiz-webhook
curl -fsS http://localhost:8421/healthz   # → {"ok": true, ...}
```

### 4b · Register with Postiz

```bash
export POSTIZ_API_URL=https://api.postiz.com
export POSTIZ_API_TOKEN=$(vault kv get -field=value contentx/postiz-token)
export CONTENTX_WEBHOOK_URL=https://hooks.contentx.internal/engagement
export CONTENTX_WEBHOOK_SECRET=$(openssl rand -hex 32)
vault kv put contentx/postiz-webhook-secret value="$CONTENTX_WEBHOOK_SECRET"
bash deploy/06_register_postiz_webhook.sh
```

**Verify:** post a manual test from Postiz; check `tail -f /var/log/postiz-webhook.log` shows the event arriving and a bead update being emitted.

---

## Step 5 · Canary run (5 min, both)

```bash
# Tier=internal first: only G1 + G14 fire
gt convoy mountain start viral_shorts \
  --tier=internal --brand=quizverse --canary=true \
  --output-dir=/tmp/canary-run-001

# Watch the gates emit
tail -f /tmp/canary-run-001/gates/*.json &
tail -f /tmp/canary-run-001/chain_of_custody.jsonl

# After convoy completes:
cat /tmp/canary-run-001/certificate.json | jq .summary

# Confirm the cert landed in cold storage
aws s3 ls s3://contentx-audit-cold/canary-run-001/
```

**Pass criteria:**
- `certificate.json` present with `passed: true`
- `chain_of_custody.jsonl` ≥ 5 entries
- S3 prefix has at least `certificate.json` and `chain_of_custody.jsonl`

---

## Step 6 · Tier progression (over a week)

| Day | Tier | Scope | Pass criteria |
|---|---|---|---|
| 1 | `internal` | rig-1 only, 5 canary runs | all certify |
| 2 | `indie`    | rig-1 only, 10 real runs | rejection rate ≤ 15% (debt surfacing) |
| 3-5 | `indie`  | all `contentx-shorts` rigs | rejection rate ≤ 5% |
| 7 | `aa`       | flagship channels w/ CD+TD signed | rejection rate ≤ 1% |
| 14 | `aaa`     | hero content | rejection rate ≤ 0.5%, all 14 gates |
| 28 | `live-aaa`| with G12 loop closed | KPI delta + cert |

---

## Decision matrix — humans must confirm before tier ≥ AA

| | Question | Owner | Default | Where to edit |
|---|---|---|---|---|
| Tier floors | Are score floors at indie/AA/AAA/Live-AAA correct? | Head of Content | indie=6.0/5.0, AA=7.0/6.5, AAA=8.0/7.5, Live=8.0/7.5 + KPI | `policies/tier_floors.toml` |
| Retention | 7y, or longer per market? | Legal | 7y (US/UK), 10y placeholder (DE/FR) | `policies/retention_policy.toml` |
| Director identities | Who's CD + TD per brand? | Brand owner | unassigned | `policies/director_assignments.toml` |
| Vault path | `vault://contentx/cert-key`? | Security | yes | this runbook |
| Override SLO | Who can `--override` and how is it scored? | VP Eng | 1 override / 100 runs = SLA breach | `policies/override_policy.toml` |

---

## Kill switches (memorize these)

```bash
# 1. One-time bypass — logged + counted against SLO
gt refinery override <run_id> --reason "ticket FOO-123" --signer <name>

# 2. Temporary tier downgrade
gt refinery set-tier viral_shorts indie --duration=1h --reason "audio infra down"

# 3. Full revert — strict 15-min cap, auto re-enables
gt refinery disable-studio-gates --duration=15m --reason "incident PAGER-2026-001"
```

All three append a signed entry to chain_of_custody.

---

## On-call playbook

| Symptom | Likely cause | Fix |
|---|---|---|
| `studio_cert: exit 1` everywhere | vault key rotated, hosts not refreshed | `systemctl restart postiz-webhook hermes-cron` on each host |
| G14 keeps reporting `hmac_invalid` | key mismatch with prior runs | `vault kv get -field=value contentx/cert-key/previous`, set as `CONTENTX_CERT_KEY_PREVIOUS`, restart |
| G10 blocks every run | new council rubric too strict | `gt refinery override` for tonight; tune rubric tomorrow |
| Postiz webhook 401s | secret drifted | rotate via step 4b, re-deploy receiver |
| S3 cost spike | versioning + lifecycle interaction | check `aws s3api list-object-versions`; lifecycle rule should expire noncurrent at 90d |

---

## Rollback

```bash
# Disable gates on rig-1 for 15 minutes
gt refinery disable-studio-gates --duration=15m

# If incident exceeds 15 minutes, the gates auto re-enable. Either:
# (a) fix the issue and let auto-enable happen, OR
# (b) re-issue --disable; if you re-issue 4 times in a row, refinery escalates to deacon
```

`disable-studio-gates` does NOT delete `chain_of_custody.jsonl` — all bypass events are preserved for audit.
