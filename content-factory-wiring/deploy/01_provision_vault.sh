#!/usr/bin/env bash
# 01_provision_vault.sh — create + rotate CONTENTX_CERT_KEY in HashiCorp Vault.
#
# Usage:
#   VAULT_ADDR=https://vault.contentx.internal \
#   VAULT_TOKEN=$(vault login -method=oidc -format=json | jq -r .auth.client_token) \
#   bash deploy/01_provision_vault.sh
#
# Effects:
#   - Creates secret at contentx/cert-key (current 32-byte hex)
#   - Archives previous key at contentx/cert-key/previous (kept 90d)
#   - Writes a policy contentx-runtime that grants read on cert-key only
#   - Prints the key version so refinery hosts can pin a specific version
set -euo pipefail

: "${VAULT_ADDR:?VAULT_ADDR must be set}"
: "${VAULT_TOKEN:?VAULT_TOKEN must be set}"

KEY=$(openssl rand -hex 32)
if [[ ${#KEY} -ne 64 ]]; then
  echo "FATAL: generated key wrong length" >&2; exit 1
fi

# Archive the existing key (if any) before overwriting
if vault kv get -field=value contentx/cert-key >/dev/null 2>&1; then
  PREV=$(vault kv get -field=value contentx/cert-key)
  vault kv put contentx/cert-key/previous value="$PREV" archived_at="$(date -u +%FT%TZ)"
  echo "previous key archived to contentx/cert-key/previous"
fi

vault kv put contentx/cert-key value="$KEY" rotated_at="$(date -u +%FT%TZ)"

# Policy: read-only access for runtime hosts
cat > /tmp/contentx-runtime.hcl <<'POLICY'
path "contentx/cert-key" {
  capabilities = ["read"]
}
path "contentx/cert-key/previous" {
  capabilities = ["read"]
}
POLICY
vault policy write contentx-runtime /tmp/contentx-runtime.hcl
rm -f /tmp/contentx-runtime.hcl

# Read back to confirm
META=$(vault kv metadata get -format=json contentx/cert-key 2>/dev/null || echo "{}")
echo ""
echo "OK — contentx/cert-key provisioned"
echo "    version : $(echo "$META" | jq -r '.data.current_version // "n/a"')"
echo "    length  : ${#KEY} chars"
echo "    rotation: monthly (set up the schedule in deploy/10_schedule_key_rotation.sh)"
echo ""
echo "On each runtime host:"
echo "    export CONTENTX_CERT_KEY=\$(vault kv get -field=value contentx/cert-key)"
