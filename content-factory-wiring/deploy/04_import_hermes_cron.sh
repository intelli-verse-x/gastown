#!/usr/bin/env bash
# 04_import_hermes_cron.sh — register all studio-grade cron jobs in Hermes.
set -euo pipefail

HERE=$(cd "$(dirname "$0")"/.. && pwd)

if ! command -v hermes >/dev/null; then
  echo "FATAL: hermes CLI not found on PATH"
  exit 1
fi

echo "==> importing cron jobs ..."
hermes cron import "$HERE/hermes/cron_jobs.yaml"

echo "==> bootstrapping Hermes SessionDB from past runs ..."
"$HERE/hermes/hermes_indexer.py" \
  --content-factory-root "${CONTENT_FACTORY_ROOT:-/Users/devashishbadlani/dev/content-factory}" \
  --sessions-db "${HERMES_SESSIONS_DB:-$HOME/.hermes/sessions.db}"

echo "==> bootstrapping Honcho personas from past runs (per brand) ..."
"$HERE/hermes/honcho_brand_persona.py" \
  --content-factory-root "${CONTENT_FACTORY_ROOT:-/Users/devashishbadlani/dev/content-factory}" \
  --output-dir "${HONCHO_PERSONA_DIR:-$HOME/.hermes/personas}"

echo "==> verifying cron registration ..."
hermes cron list | grep -E "engagement_24h|daily_slate_prep" || {
  echo "FATAL: expected cron entries not registered"
  exit 1
}

echo ""
echo "hermes deploy complete"
