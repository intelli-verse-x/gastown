# viral_shorts · first-cut scaffolding

Three artifacts, runnable end-to-end after `NS-1` deploy:

1. **`bootstrap_beads.sh`** — creates the epic + parent beads for ongoing viral_shorts work
2. **`mountain.yaml`** — the canonical viral_shorts mountain convoy (per-day shape)
3. **`hermes_skills/`** — 5 skills the planner consults *before* every viral_shorts run

The shape mirrors `configs/convoys.yaml`'s viral_shorts entry but expanded into
real `bd create` / `gt mountain` / `hermes` invocations. Everything below is
copy-pasteable.

---

## 0. One-time bootstrap (run once per rig)

```bash
# Make sure you're inside a beads-initialized dir
cd ~/.gastown/rigs/contentx-shorts
bd init    # safe to re-run; no-op if already initialized

# Register the formula so `gt formula run viral-shorts-daily` works
mkdir -p .beads/formulas
cp /opt/contentx-wiring/scaffolding/viral_shorts/mountain.yaml \
   .beads/formulas/viral-shorts-daily.toml

# Register the auto-skills with Hermes
hermes skill register /opt/contentx-wiring/scaffolding/viral_shorts/hermes_skills/

# Bootstrap the parent epic
bash /opt/contentx-wiring/scaffolding/viral_shorts/bootstrap_beads.sh
```

## 1. Daily run kickoff

```bash
# Either cron-driven (already in hermes/cron_jobs.yaml as contentx-daily-shorts)…
# or manual:
gt formula run viral-shorts-daily \
  --brand=quizverse \
  --slate=/var/lib/content-factory/slates/$(date +%Y-%m-%d).json \
  --tier=aa

# Watch progress
gt mountain status $(gt convoy list --label=viral-shorts --label=mountain --json | jq -r '.[0].id')
gt trail --rig=contentx-shorts | head -40
```

## 2. The 5 pre-script skills (Hermes consults before every run)

```
hermes_skills/
├── 01-tighten-hook.md           # derived from 11 instances of "Auto-pass: time budget exhausted"
├── 02-fix-dead-spots.md         # derived from 2x "Fix dead spot 0:08-0:12"
├── 03-inject-engagement.md      # derived from "Insert 'Comment your guess!' prompt"
├── 04-audio-master-loudnorm.md  # derived from the F2 audio_quality failures
└── 05-add-captions.md           # derived from 18 M11_caption_missing findings
```

Each one is a real Hermes skill — front-matter + body — that the planner
loads into context (`hermes /context viral_shorts` → top-K skills cached).

## 3. Refinery gates that block this pipeline

When `gt sling done <bead> --merge=mr` fires, refinery runs every gate listed
in `configs/refinery.toml` under `tier_policy.aa`:

```
G_script_present · G_no_blocker_gaps · G_audio_passed · G_guard_ran ·
G_delivery_passed · G_council_applied · G_checkpoint_clean ·
G_graph_state_valid · G_no_nested_duplication · G_rights_manifest ·
G_brand_compliance · G_council_score_floor
```

Any FAIL emits an `S2_gate_fail` bead with severity matching the gate's
`severity_on_fail` and routes to the polecat declared as that gate's `auditor`.
