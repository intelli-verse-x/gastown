# content-factory-wiring

**Status:** runnable end-to-end against real `/Users/devashishbadlani/dev/content-factory/.working_dir/`.
**Audience:** Mayor & on-call. Read `runbooks/OPERATOR_RUNBOOK.md` first.

## What this is

The four-section strategic analysis (F1-F6 failure modes → gas-town primitives →
hermes learning loop → quantified quality impact) reified as runnable code, configs,
and reports. Nothing here is a placeholder.

```
┌─ tools/        Python — auditor, repairer, KPI tracker
├─ configs/      .gastown — refinery, witness, convoys (+ quizverse sub-mountain)
├─ hermes/       Hermes — indexer, scraper, cron, auto-skills
├─ reports/      live data — re-run tools/ to refresh
└─ runbooks/     OPERATOR_RUNBOOK.md (read this)
```

## Live numbers from this bundle

| Surface | Pre-wiring | Wired |
|---|---|---|
| content-factory runs sampled | 9 | 9 |
| Grade-F runs | 8/9 (89%) | tracked by witness |
| Council directives ignored | 79 across 9 runs | becomes 403 beads |
| Blocker gaps silenced | 24 | each escalates via `gt escalate` |
| QuizVerse characters audited | 0 | 15 (160 flaws total) |
| Quizzy defect score | 157 (F) | 12 (✅) — 92% reduction proof |
| Total actions auto-generated | 0 | 532 (`bd` + `gt`) |
| Hermes auto-skills proposed | — | 7 (from real recurring directives) |

## One-command sanity check

```bash
cd /Users/devashishbadlani/dev/gastown/content-factory-wiring
python3 tools/run_id_auditor.py \
  --batch /Users/devashishbadlani/dev/content-factory/.working_dir/video 2>&1 | tail -12
```

Should print 9 runs, 8 grade F, 1 grade D, ~196 findings.

## Two-step approval to operationalize

1. **Look at the two comparison images** (`reports/quizzy_01_*.png` and `reports/quizzy_02_*.png`).
2. **Pick a path:**
   - **One-click:** `bd close qv-quizzy --comment "Recipe approved"` then
     `gt mountain start quizverse-art-cert-redelivery`.
     The 14 remaining characters land in your `bd ready` queue with Telegram
     approval requests.
   - **Per-character:** `gt mountain start quizverse-art-cert-redelivery --human-approve-per-character`.
     Each character is gated on your `Approve / Reject` reply.
   - **Hold for review:** Just keep poking around `reports/quizverse_full_audit.json`.
     Nothing has been touched in S3.

## Provenance & re-derivation

Every report in `reports/` is reproducible. The seed data is real:
- 9 viral_shorts runs in `/Users/devashishbadlani/dev/content-factory/.working_dir/video/`
- 15 character asset bundles downloaded from the QuizVerse S3 manifest
- 1 Quizzy fix recipe applied + measured (`/tmp/quizverse-audit/fix_quizzy.py`)

To regenerate from scratch:

```bash
# 1. audits
python tools/run_id_auditor.py --batch <working_dir>/video --out reports/batch_audit_video.json
# 2. repair plan
python tools/run_id_repairer.py reports/batch_audit_video.json \
  --emit-beads reports/all_beads.jsonl \
  --emit-script reports/apply_all_repairs.sh
# 3. hermes KB
python hermes/hermes_indexer.py --db reports/hermes_contentx.sqlite \
  --batch <working_dir> --propose-skills --skill-threshold=3 \
  --out-skills hermes/skills_auto
# 4. KPI digest
python tools/kpi_tracker.py
```

All four scripts are idempotent.
