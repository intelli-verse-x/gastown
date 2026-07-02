---
name: contentx-tighten-hook
description: "Pre-empt the council's 'Hook score < 6' directive before the script is written."
trigger: "pipeline.kind == 'viral_shorts'"
phase: "pre_script_planner"
derived_from: 2_council_directives + 11_time_budget_passes
applies_at: planner
priority: high
---

# Tighten hook — pre-script skill

## Why this exists

Across the 9 audited viral_shorts runs, the council surfaced the **"Hook score < 6"**
directive multiple times — and 11 of those audits were short-circuited as
`"Auto-passed: council time budget exhausted"`, so the fix never landed in the
pipeline. The directive recurs because the planner doesn't know what a 7+ hook
looks like for this brand.

## Hook spec the planner must satisfy

A hook scores ≥ 7 when **all** of the following hold for 0:00 → 0:03:

1. **Audio attack ≤ 200 ms** — first audible peak within 200 ms of frame 0
2. **Visual motion ≥ 20%** — first 3 s has at least 30 sampled frames (10 fps)
3. **Content payload by 0:01** — the *what* of the video must be conveyed by the
   1-second mark. Acceptable forms: question, claim, character entry,
   numeric reveal.
4. **No logo intro, no slow zoom, no static text card** as the first beat.
5. **Brand voice cold-open** — first words spoken must be in the brand's
   preferred voice (Honcho persona's `preferred_voices[0]`).

## Pre-script directive (insert into planner system prompt)

```
HOOK CONSTRAINT (mandatory):
- frames 0-0:03 score ≥ 7 against the brand persona's "hook" rubric
- if the draft's first beat is a logo/slow-zoom/static card, reject and
  redraft with a question or numeric reveal in its place
- include exactly one of: "did you know", "what if", "watch this",
  "[N]/[10] people", "in 3 seconds you'll" — chosen to fit the topic,
  not pasted blindly
```

## Verification (auditor wires this back)

If `council_audits/hook_writing_audit.json.hook_score < 6`:
- bead created with label `F3_council_unapplied + hook`
- redo subagent spawned (respects `max_redos`)
- this skill's `confidence` decremented; if `< 0.5`, the skill is flagged
  for review by the auto-skill-creator
