#!/usr/bin/env bash
# 03_deploy_refinery.sh — load studio-gate config into refinery.
#
# Safe to re-run; refinery reload is idempotent.
set -euo pipefail

HERE=$(cd "$(dirname "$0")"/.. && pwd)

echo "==> validating configs locally first ..."
python3 -c "
import tomllib, sys
for f in [
    '$HERE/configs/refinery.toml',
    '$HERE/configs/refinery_viral_shorts.toml',
]:
    with open(f, 'rb') as fh:
        try: tomllib.load(fh)
        except tomllib.TOMLDecodeError as e:
            print(f'INVALID: {f}: {e}'); sys.exit(1)
    print(f'  OK {f}')
"

echo "==> refinery reload ..."
gt refinery reload \
  --config "$HERE/configs/refinery.toml" \
  --pipeline-overlay "$HERE/configs/refinery_viral_shorts.toml"

echo "==> witness rules ..."
gt witness reload --config "$HERE/configs/witness.yaml"

echo "==> convoy shapes ..."
gt convoy shapes reload --config "$HERE/configs/convoys.yaml"

echo "==> verifying refinery sees all 14 studio gates ..."
COUNT=$(gt refinery list-gates --json 2>/dev/null | jq '[.[] | select(.kind=="studio_gate")] | length')
if [[ "$COUNT" -ne 14 ]]; then
  echo "FATAL: refinery reports $COUNT studio gates, expected 14"
  exit 1
fi
echo "  refinery sees 14/14 studio gates"

echo ""
echo "refinery deploy complete"
