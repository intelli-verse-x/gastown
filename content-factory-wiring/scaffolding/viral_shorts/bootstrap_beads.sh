#!/usr/bin/env bash
# bootstrap_beads.sh — one-time setup for the viral_shorts rig.
# Run inside the rig directory after `bd init`.
#
# Creates:
#   1 epic (parent)
#   8 child task beads (one per pipeline phase)
#   3 P0 systemic-fix beads (NS-3a/b + caption pipeline)
#
# Idempotent: rerunning will add duplicates, so guard with `bd list` if needed.

set -euo pipefail

command -v bd >/dev/null || { echo "bd not found in PATH"; exit 1; }

# ------------------------------------------------------------------ Epic
# Parse "Created issue: <prefix>-<hash>" — prefix is whatever `bd init` chose for this repo
EPIC=$(bd create "viral_shorts: continuous quality program" \
  --type=epic --priority=1 \
  --labels=content-factory,viral_shorts,program \
  --description="Track per-day viral_shorts runs and roll up grade-A rate as the parent KPI. Every daily mountain hangs off this epic." \
  | grep -oE '[A-Za-z0-9-]+-[a-z0-9]+' | head -1)
[ -z "$EPIC" ] && { echo "failed to capture epic id"; exit 1; }

echo "EPIC: $EPIC"

# ------------------------------------------------------------------ Phase tasks
declare -a PHASES=(
  "ideation:Pre-script planner consults Hermes skills before generating ideas"
  "script:Draft + canon-lock script with brand persona constraints"
  "director_brief:Resolve aspect_ratio + duration_seconds from PipelineContext"
  "reference_images:Generate visual style refs (mood-locked via Honcho persona)"
  "video_generation:Per-scene subagent fan-out (max_concurrent=4)"
  "audio_master:Loudnorm to platform LUFS + true-peak gate"
  "council_audit:Apply directives via redo subagent (respects max_redos)"
  "delivery_gate:Run social_publish_auditor before any postiz call"
)

for p in "${PHASES[@]}"; do
  phase=${p%%:*}
  desc=${p#*:}
  bd create "viral_shorts phase: $phase" \
    --type=task --priority=2 \
    --parent="$EPIC" \
    --labels=content-factory,viral_shorts,phase,$phase \
    --description="$desc"
done

# ------------------------------------------------------------------ P0 systemic fixes (NS-3a/b + NS-6)
bd create "Council time-budget short-circuit auto-passes failed audits (NS-3a)" \
  --type=bug --priority=0 \
  --parent="$EPIC" \
  --labels=content-factory,council,P0,viral_shorts \
  --description=$'agents/council/runner.py auto-passes the audit when elapsed > budget_seconds. Change to DEFER + blocker_unless_resumed=true. Fires 11x across the 9 audited viral_shorts runs.'

bd create "guard.run_all() not invoked across viral_shorts (NS-3b)" \
  --type=bug --priority=0 \
  --parent="$EPIC" \
  --labels=content-factory,guard,P0,viral_shorts \
  --description=$'8 of 9 viral_shorts runs report guard_summary.total_checks=0. Wire QualityGuard.run_all() into the delivery phase before publish.'

bd create "social_publish_auditor as pre-publish CI hook (NS-6)" \
  --type=feature --priority=1 \
  --parent="$EPIC" \
  --labels=content-factory,refinery,viral_shorts \
  --description=$'Bind tools/social_publish_auditor.py to the publish phase. Any blocker/critical finding exits 1 and emits a refinery bead. Closes F10 permanently.'

echo
echo "bootstrap complete — top of the epic tree:"
bd children "$EPIC" | head -20
