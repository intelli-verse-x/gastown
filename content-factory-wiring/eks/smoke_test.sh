#!/usr/bin/env bash
# eks/smoke_test.sh — end-to-end smoke test against the deployed webhook.
#
# Modes:
#   local           build + run docker container locally; curl through 127.0.0.1
#   k8s             port-forward to the in-cluster pod; curl through 127.0.0.1
#   url <URL>       hit the given URL directly (e.g. ALB or ingress hostname)
#
# Pass criteria (all must be true):
#   1.  /healthz returns {"ok": true, ...}
#   2.  POST /engagement with VALID HMAC returns 200/202 + JSON
#   3.  POST /engagement with INVALID HMAC returns 401
#   4.  /metrics shows postiz_webhook_received_total >= 2 AND signature_invalid_total >= 1
set -euo pipefail

MODE="${1:-k8s}"
NAMESPACE="${NAMESPACE:-content-factory}"

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
blue()   { printf "\033[34m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

# Recover the cert key from the last deploy (script writes it to /tmp)
if [[ -f /tmp/contentx-deploy-last/.webhook_secret ]]; then
  WEBHOOK_SECRET=$(cat /tmp/contentx-deploy-last/.webhook_secret)
else
  yellow "no recent deploy state — falling back to in-cluster secret"
  WEBHOOK_SECRET=$(kubectl -n "$NAMESPACE" get secret contentx-webhook-secrets \
                   -o jsonpath='{.data.CONTENTX_WEBHOOK_SECRET}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
fi
if [[ -z "$WEBHOOK_SECRET" ]]; then
  red "could not load CONTENTX_WEBHOOK_SECRET"
  exit 2
fi

# ---------------------------------------------------------------------------
# Set up the target URL
# ---------------------------------------------------------------------------
PF_PID=""
cleanup() {
  if [[ -n "${PF_PID}" ]]; then
    kill "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

case "$MODE" in
  local)
    blue "==> mode: local docker"
    docker rm -f contentx-smoke 2>/dev/null || true
    docker run -d --rm --name contentx-smoke \
      -e CONTENTX_WEBHOOK_SECRET="$WEBHOOK_SECRET" \
      -e CONTENTX_CERT_KEY="$(openssl rand -hex 32)" \
      -p 18421:8421 \
      "${IMAGE:-contentx-postiz-webhook:smoke}" >/dev/null
    BASE="http://127.0.0.1:18421"
    sleep 3
    ;;
  k8s)
    blue "==> mode: k8s port-forward"
    kubectl -n "$NAMESPACE" rollout status deploy/contentx-postiz-webhook --timeout=60s
    kubectl -n "$NAMESPACE" port-forward svc/contentx-postiz-webhook 18421:80 >/tmp/pf.log 2>&1 &
    PF_PID=$!
    BASE="http://127.0.0.1:18421"
    sleep 3
    ;;
  url)
    BASE="${2:?usage: smoke_test.sh url <URL>}"
    ;;
  *)
    red "unknown mode: $MODE (use local|k8s|url <URL>)"
    exit 2
    ;;
esac

# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
report() {
  local name="$1" ok="$2" detail="$3"
  if [[ "$ok" == "1" ]]; then
    green "  PASS  $name  $detail"
    PASS=$((PASS+1))
  else
    red "  FAIL  $name  $detail"
    FAIL=$((FAIL+1))
  fi
}

blue "==> probes against $BASE"

# Probe 1 — /healthz
HZ=$(curl -fsS -m 5 "$BASE/healthz" 2>/dev/null || echo "")
OK=$(echo "$HZ" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(int(d.get("ok",False)))' 2>/dev/null || echo "0")
report "P1 healthz returns ok=true" "$OK" "$(echo "$HZ" | head -c 80)"

# Probe 2 — valid HMAC
BODY='{"post_id":"smoke-test-001","event":"post.engagement.24h","platform":"youtube_shorts","metrics":{"views":1234,"likes":42}}'
SIG_VALID="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $2}')"
RESP_VALID=$(curl -s -o /tmp/resp_valid.json -w "%{http_code}" -X POST "$BASE/engagement" \
  -H "X-Postiz-Signature: $SIG_VALID" -H "Content-Type: application/json" -d "$BODY" -m 5)
if [[ "$RESP_VALID" == "200" || "$RESP_VALID" == "202" ]]; then
  report "P2 valid HMAC -> 2xx" "1" "http $RESP_VALID"
else
  report "P2 valid HMAC -> 2xx" "0" "got http $RESP_VALID, body: $(head -c 80 /tmp/resp_valid.json)"
fi

# Probe 3 — invalid HMAC
RESP_INVALID=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/engagement" \
  -H "X-Postiz-Signature: sha256=00000000000000000000000000000000" \
  -H "Content-Type: application/json" -d "$BODY" -m 5)
if [[ "$RESP_INVALID" == "401" ]]; then
  report "P3 invalid HMAC -> 401" "1" "http 401"
else
  report "P3 invalid HMAC -> 401" "0" "got http $RESP_INVALID"
fi

# Probe 4 — metrics
METRICS=$(curl -fsS -m 5 "$BASE/metrics" 2>/dev/null || echo "")
# Skip the "# TYPE foo counter" line; pick the numeric-only line.
RECV=$(echo "$METRICS"    | awk '$1=="postiz_webhook_received_total"          {print $2; exit}')
SIG_INV=$(echo "$METRICS" | awk '$1=="postiz_webhook_signature_invalid_total" {print $2; exit}')
RECV=${RECV:-0}; SIG_INV=${SIG_INV:-0}
if (( RECV >= 2 && SIG_INV >= 1 )); then
  report "P4 metrics counters incrementing" "1" "received=$RECV signature_invalid=$SIG_INV"
else
  report "P4 metrics counters incrementing" "0" "received=$RECV signature_invalid=$SIG_INV"
fi

# Local cleanup
if [[ "$MODE" == "local" ]]; then
  docker rm -f contentx-smoke 2>/dev/null || true
fi

echo ""
if (( FAIL == 0 )); then
  green "============================================================"
  green "  SMOKE TEST PASSED   ${PASS}/${PASS}"
  green "============================================================"
  exit 0
else
  red "============================================================"
  red "  SMOKE TEST FAILED   ${PASS} passed, ${FAIL} failed"
  red "============================================================"
  exit 1
fi
