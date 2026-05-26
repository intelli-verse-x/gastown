---
name: contentx-inject-engagement
description: "Insert a single engagement trigger per 15 s of runtime, placed for max retention."
trigger: "pipeline.kind in ['viral_shorts', 'short_video']"
phase: "script"
derived_from: 5_distinct_recurring_directives ("Insert 'Comment your guess!'")
applies_at: scripter
priority: medium
---

# Inject engagement triggers — script-phase skill

## Pattern observed

The KB shows **5 separate council directives** that all say the same thing:
"Zero engagement triggers — insert a 'Comment your X!' prompt at [N]:[NN]."

The directives recur in 5 different audit phases (brief_validation, video,
publish_metadata, compliance, screenwriting). The script-phase fix below
deduplicates them.

## Rule

For every 15 s of runtime, the script must include **exactly one** engagement
trigger. Phrasing rotates per video (no copy-paste of the same prompt across
the brand's catalog).

| Runtime | Triggers | Allowed positions |
|---|---|---|
| ≤ 15 s | 1 | 0:08–0:12 |
| 16–30 s | 2 | 0:08–0:12 + 0:20–0:25 |
| 31–60 s | 3 | 0:08, 0:25, 0:45 |

## Phrasing rotation

Cycle through the persona's preferred forms, never repeat the last 3:
1. "Comment your guess"
2. "Tap a reaction if you got it"
3. "Drop a [emoji] if [premise]"
4. "[N]/10 people fail this — see if you're the [N]"
5. "Reply with [keyword] if you want part 2"

The Honcho persona's `engagement_phrasing_blocklist` field (auto-populated from
past low-engagement runs) is the negative prompt — never use those forms.

## Verification

`council/screenwriting_audit.json.engagement_triggers_n` must equal the
expected count for the runtime. The auditor reads timestamps from the script
and verifies they're spaced according to the table above.
