#!/usr/bin/env bash
# run_all.sh — orchestrate full deploy. Stops on first failure.
#
# Run only on the FIRST host. On subsequent hosts, run 02_bootstrap_host.sh + 03_deploy_refinery.sh + 04_import_hermes_cron.sh only.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)

echo "============================================================"
echo "  CONTENT-FACTORY STUDIO GATES — FULL DEPLOY"
echo "============================================================"

bash "$HERE/01_provision_vault.sh"
export CONTENTX_CERT_KEY=$(vault kv get -field=value contentx/cert-key)

bash "$HERE/02_bootstrap_host.sh"
bash "$HERE/03_deploy_refinery.sh"
bash "$HERE/04_import_hermes_cron.sh"
bash "$HERE/05_setup_s3_audit_cold.sh"
bash "$HERE/06_register_postiz_webhook.sh"

echo ""
echo "============================================================"
echo "  POST-DEPLOY VERIFY"
echo "============================================================"
python3 "$HERE/../tools/studio_gates/post_deploy_verify.py" || {
  echo "DEPLOY FAILED — verifier reports red"
  exit 1
}

echo ""
echo "DEPLOY COMPLETE"
echo "Next: run a canary"
echo "  gt convoy mountain start viral_shorts --tier=internal --canary=true"
