# Content-Factory ↔ Gas-Town ↔ Hermes — Operator Runbook

**Version:** 1.0 · **Generated:** by the wiring build · **Audience:** Mayor / Sheriff / on-call

This bundle wires content-factory's `run_id` to the gas-town backbone and the
Hermes cognitive loop, exactly as proposed in the strategic analysis. Every
piece is in this folder, runnable, and points at real working_dir folders.

---

## 0. What you'll find here

```
content-factory-wiring/
├── tools/
│   ├── run_id_auditor.py            # F1-F6 detector
│   ├── run_id_repairer.py           # findings → bd/gt commands
│   └── kpi_tracker.py               # KPI dashboard vs targets
│
├── configs/
│   ├── refinery.toml                # cert gates, tier policy, escalation routes
│   ├── witness.yaml                 # patrol rules, polecat templates
│   ├── convoys.yaml                 # per-pipeline-kind convoy shapes
│   └── quizverse/                   # the 15-character art-cert mountain
│       ├── refinery.toml
│       ├── mountain.yaml
│       ├── beads.jsonl
│       └── signoff_dashboard.md
│
├── hermes/
│   ├── hermes_indexer.py            # bootstrap FTS5 KB from past runs
│   ├── postiz_engagement_scraper.py # browser_provider hook for engagement
│   ├── cron_jobs.yaml               # all scheduled jobs
│   └── skills_auto/                 # 7 auto-derived skills from real runs
│
├── reports/                         # live data — regenerate by running tools/
│   ├── batch_audit_video.json       # F1-F6 across 9 viral_shorts runs
│   ├── batch_repair_plan.json       # 532 actions across 9 runs
│   ├── all_beads.jsonl              # 403 beads ready for `bd import`
│   ├── apply_all_repairs.sh         # one-shot repair script
│   ├── hermes_contentx.sqlite       # FTS5 KB
│   ├── quizverse_full_audit.json    # 160 flaws across 15 characters
│   ├── quizverse_quizzy_delta.json  # 92% defect reduction proof
│   └── kpi_digest.md                # vs the team's own targets
│
└── runbooks/
    └── OPERATOR_RUNBOOK.md          # this file
```

---

## 1. The numbers you're inheriting

### 1a. content-factory run-lifecycle audit (9 viral_shorts runs sampled)

| Failure mode | Findings | What it means |
|---|---:|---|
| F1 silent abort        |  8 / 9 runs | Pipelines aborted without alerting anyone |
| F2 gate-fail-but-ship  |  4 incidents | Audio failed QC, asset still shipped |
| F2b guard never ran    |  8 / 9 runs | `guard_summary.total_checks=0` |
| F3 council unapplied   | **403** beads worth | 79 council audits with directives, redo_count=0 |
| F4 blocker silenced    | 24 incidents | `missing_script` blocker ignored 24 times |
| F5 open feedback       | 12 stubs | run_feedback.json never closed |
| F6 nested duplication  |  9 runs | production/production/scenes/... duplicates |

**8 of 9 runs grade F, 1 grade D, total weighted defect score across 9: ~1,970.**

### 1b. QuizVerse art-cert audit (all 15 characters)

| Character | Flaws | Blockers | Critical | Score | Grade |
|---|---:|---:|---:|---:|:---:|
| Quizzy_v2   | 35 | 9 | 22 | 420 | F |
| Quizzy      | 23 | 9 | 13 | 315 | F |
| Quizzy_v1   | 21 | 9 | 11 | 295 | F |
| AUTOcurio   | 11 | 2 |  7 | 120 | F |
| IX          | 10 | 2 |  6 | 110 | F |
| Pixel       | 11 | 0 |  7 |  90 | D |
| Nova        |  8 | 0 |  5 |  65 | D |
| Sparky      |  7 | 0 |  6 |  65 | D |
| Bear        |  7 | 0 |  5 |  60 | D |
| Echo        |  7 | 0 |  5 |  60 | D |
| Professor   |  5 | 0 |  4 |  45 | C |
| Luna        |  4 | 0 |  4 |  40 | C |
| Atlas       |  4 | 0 |  3 |  35 | C |
| Dog         |  4 | 0 |  3 |  35 | C |
| Duck        |  3 | 0 |  3 |  30 | C |
| **TOTAL**   | **160** | **31** | **104** | **1,785** | — |

**3 sprite sheets fully empty** (AUTOcurio attack/hurt, IX hurt) — manifest said "fixed".
**1 asset corrupt** (IX/back_nobg.png cannot decode).
**Quizzy fixed end-to-end as proof: 92% defect reduction** (157 → 12).

---

## 2. Monday-morning starter sequence

Run these in order to operationalize everything:

```bash
cd /Users/devashishbadlani/dev/gastown/content-factory-wiring

# 1. Re-audit all current runs (always start with fresh data)
python tools/run_id_auditor.py \
  --batch /Users/devashishbadlani/dev/content-factory/.working_dir/video \
  --out reports/batch_audit_video.json

# 2. Generate the repair plan (becomes beads + escalations)
python tools/run_id_repairer.py reports/batch_audit_video.json \
  --emit-beads reports/all_beads.jsonl \
  --emit-script reports/apply_all_repairs.sh \
  --out reports/batch_repair_plan.json

# 3. Look at the plan before applying
head -40 reports/apply_all_repairs.sh
wc -l reports/all_beads.jsonl  # should be ~400+ beads

# 4. Apply (each line is bd create / gt escalate / gt nudge — non-destructive,
#    these create beads, they don't touch any video file)
bash reports/apply_all_repairs.sh

# 5. Bootstrap Hermes' memory from all historical runs
python hermes/hermes_indexer.py \
  --db reports/hermes_contentx.sqlite \
  --batch /Users/devashishbadlani/dev/content-factory/.working_dir \
  --propose-skills --skill-threshold=3 \
  --out-skills hermes/skills_auto

# 6. Register cron jobs (one-time)
hermes cron import hermes/cron_jobs.yaml

# 7. Install refinery + witness configs (replace existing if any)
cp configs/refinery.toml ~/.gastown/refinery/content-factory.toml
cp configs/witness.yaml ~/.gastown/witness/content-factory.yaml
cp configs/convoys.yaml ~/.gastown/convoys/content-factory.yaml
gt rig reload content-factory

# 8. KPI snapshot vs targets
python tools/kpi_tracker.py
```

After step 4 you should see a slew of new beads in `bd ready`. After step 6
witness is patrolling every 30s. After step 7 refinery will start blocking
any new run that doesn't pass the gates.

---

## 3. Per-failure-mode operator commands

### F1 — Silent abort recovery
```bash
# Find aborted runs not yet picked up
bd list --labels=F1,content-factory --status=open

# Resume a specific one manually
gt nudge contentx-shorts/resume \
  --bead qv-run-viral_shorts_20260420_032142_a9380cd7 \
  -m "manual restart from operator"
```

### F2 — Gate-fail-but-ship blockade
```bash
# Refinery will reject from now on. Check what's queued:
gt sling status content-factory

# Inspect a rejected MR
gt sling show <mr-id>

# Override only with overseer approval:
gt sling approve <mr-id> --override --reason="..." --approver=overseer
```

### F3 — Council directive replay
```bash
# View directives still unapplied
sqlite3 reports/hermes_contentx.sqlite \
  "SELECT run_id, audit_phase, COUNT(*) FROM directives WHERE applied=0
   GROUP BY run_id, audit_phase ORDER BY COUNT(*) DESC LIMIT 20"

# Dispatch a redo convoy for one run
gt convoy create --type=mountain --parent=qv-run-<id> \
  --name="apply-directives" --max-concurrent=3 --sla-hours=2
```

### F4 — Blocker gap escalation
```bash
# Auto-escalated by the repairer; check the bead board:
bd list --priority=0 --labels=F4

# Force-pull the script_gap blocker
gt escalate --severity=CRITICAL --route=mayor --bead=<bead-id>
```

### F5 — Engagement loop closure
```bash
# Triggered automatically every 6h by cron. To run manually:
python hermes/postiz_engagement_scraper.py \
  --db reports/hermes_contentx.sqlite \
  --working-dir /Users/devashishbadlani/dev/content-factory/.working_dir

# View collected engagement
sqlite3 reports/hermes_contentx.sqlite \
  "SELECT run_id, platform, hours_post_pub, views, completion_rate
   FROM engagement ORDER BY measured_at DESC LIMIT 30"
```

### F6 — Dedup nested state files
```bash
# Dry-run plan:
python tools/run_id_repairer.py reports/batch_audit_video.json \
  --out reports/dedup_plan.json

# Apply (symlinks duplicates to canonical at root)
python tools/run_id_repairer.py reports/batch_audit_video.json \
  --apply-f6 --run-path /Users/devashishbadlani/dev/content-factory/.working_dir/video/<run_id>
```

---

## 4. QuizVerse art-cert sign-off (15-character mountain)

Look at the two before/after images in `reports/`:
- `quizzy_01_transparency.png` — opaque white BG → checkerboard transparency
- `quizzy_02_master_atlas.png` — 6 separate sheets → 1 unified 6×6 atlas

If you sign off:
```bash
# Accept Quizzy as the reference fix
bd close qv-quizzy --comment "Recipe approved. Apply to remaining 14."

# Kick the mountain
gt mountain start quizverse-art-cert-redelivery
# OR per-character review:
gt mountain start quizverse-art-cert-redelivery --human-approve-per-character
```

The mountain will:
1. Re-audit all 14 in parallel (~3 min)
2. Apply the Quizzy recipe in batches of 4 (~12 min)
3. Re-audit, gate on ≥80% defect reduction
4. Telegram-dispatch each character to you with thumbnail + delta
5. Sign cert files + republish to S3 under `agent-assets/games/quiz-verse/cert/<char>/`

**AUTOcurio attack + hurt + IX hurt will fail at step 3** (empty sprite sheets need
regeneration, not patching). The polecat will auto-escalate via
`gt escalate --severity=HIGH --route=mayor "<char> needs regeneration"` and the
regen bead lands in a separate convoy that calls your image generator with the
master style guide. Other 11 keep flowing.

---

## 5. KPI dashboard — vs the team's own targets

```bash
python tools/kpi_tracker.py --weekly
```

The targets come straight from `docs/MEMORY_FEEDBACK_LOOP_IMPACT.md`. The tracker
hits ❌ on every row today; expect to clear most ❌ → ✅ within 30 days of
operationalizing this bundle. Specific signals to watch first:

| Watch this first | Why |
|---|---|
| `silent_abort_rate` | Easiest immediate win — witness catches everything from day 1 |
| `guard_actually_ran` | A code-level wiring fix; should go 11% → 100% in one PR |
| `council_directive_apply_rate` | Hardest. Needs redo convoys actually running |
| `blocker_gaps_silenced_rate` | Refinery enforces this — should drop to 0% as soon as deployed |
| `feedback_loop_closure_rate` | Cron job runs every 6h, count climbs daily |

---

## 6. The exact failure surface, attributed

Every red number above maps to one of three layers:

| Layer | What's broken | Files / configs that fix it |
|---|---|---|
| **Pipeline code** | F2b guard never invoked, F6 nested writes, hardcoded literals (24 narrator_style, 6 mood) | content-factory PRs (out of scope for this bundle) |
| **Operational** | F1/F2/F4 (no enforcement, no recovery, no alerting) | `configs/refinery.toml`, `configs/witness.yaml`, `tools/run_id_*` |
| **Cognitive** | F3/F5 (council ignored, no engagement learning) | `hermes/*.py`, `hermes/cron_jobs.yaml`, auto-skills |

Run this bundle end-to-end and:
- The **operational** layer becomes enforced (refinery + witness + escalations)
- The **cognitive** layer starts learning (hermes_indexer + postiz_scraper + auto-skills)
- The **pipeline code** issues become tracked beads with concrete remediation,
  not silently-shipped failures.

---

## 7. What I haven't done (next sprint candidates)

- **Wire the pipeline-code fixes from PIPELINE_CONTEXT_GAP_ANALYSIS** — those need
  PRs into content-factory (24 narrator_style sites, 6 mood literals, hardcoded
  aspect_ratio / duration_seconds families).
- **Actual MCP exposure of generators** (Veo / ElevenLabs / Kling) — the contract
  is documented in the section-3 mapping; the wrapper code is a separate workstream.
- **ACP adapter** between pipelines so they can call each other as typed agents.
- **Honcho persona bootstrap** for the top 10 brands — needs a brand-by-brand
  baseline pull from S3, then a 1-shot embedding script.

These four together are what closes section 3's last column. They're all
within ~2 weeks of work; the *backbone* (this bundle) is what makes them
worth doing.

---

*Bundle hash: derive at install time via `sha256sum -r tools/* configs/* hermes/*`.*
*Owner: Mayor. Backup: Sheriff on rotation.*
