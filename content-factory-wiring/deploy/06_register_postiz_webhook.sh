#!/usr/bin/env bash
# 06_register_postiz_webhook.sh — register the engagement-update webhook
# with Postiz so that platform analytics flow back into beads.
#
# Requires:
#   POSTIZ_API_URL          — Postiz API root (e.g., https://api.postiz.com)
#   POSTIZ_API_TOKEN        — Postiz API token with webhook:create
#   CONTENTX_WEBHOOK_URL    — public URL of services/postiz_webhook
#   CONTENTX_WEBHOOK_SECRET — shared secret for HMAC body verification
set -euo pipefail

: "${POSTIZ_API_URL:?POSTIZ_API_URL must be set}"
: "${POSTIZ_API_TOKEN:?POSTIZ_API_TOKEN must be set}"
: "${CONTENTX_WEBHOOK_URL:?CONTENTX_WEBHOOK_URL must be set (e.g. https://hooks.contentx.internal/engagement)}"
: "${CONTENTX_WEBHOOK_SECRET:?CONTENTX_WEBHOOK_SECRET must be set}"

echo "==> registering webhook at $POSTIZ_API_URL/webhooks ..."
RESP=$(curl -sf -X POST "$POSTIZ_API_URL/webhooks" \
  -H "Authorization: Bearer $POSTIZ_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<JSON
{
  "url": "$CONTENTX_WEBHOOK_URL",
  "secret": "$CONTENTX_WEBHOOK_SECRET",
  "events": [
    "post.published",
    "post.engagement.update",
    "post.engagement.24h",
    "post.engagement.72h",
    "post.engagement.7d"
  ]
}
JSON
)
echo "$RESP" | jq .

WEBHOOK_ID=$(echo "$RESP" | jq -r '.id')
if [[ -z "$WEBHOOK_ID" || "$WEBHOOK_ID" == "null" ]]; then
  echo "FATAL: webhook registration failed"
  exit 1
fi

echo "$WEBHOOK_ID" > /etc/contentx/postiz_webhook_id 2>/dev/null \
  || mkdir -p ./.deploy && echo "$WEBHOOK_ID" > ./.deploy/postiz_webhook_id

echo ""
echo "Postiz webhook registered: $WEBHOOK_ID"
echo "  events  : post.published, post.engagement.{update,24h,72h,7d}"
echo "  target  : $CONTENTX_WEBHOOK_URL"
echo "  secret  : in vault://contentx/postiz-webhook-secret"
