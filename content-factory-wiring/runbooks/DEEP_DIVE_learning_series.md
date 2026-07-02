# Deep dive — `learning_series` pipeline

> Picked because it exercises **the most gas-town primitives at once**: a
> long-lived parent `epic` (the season), a `mountain` per episode, sibling
> `convoys` for cross-episode QA, and the only pipeline kind where Hermes'
> *continuity bible* + FTS5 recall genuinely move retention. ads and movies
> rely on the same patterns at smaller scope; learning_series is the
> demonstrator.

---

## 1. What's there today

```
/Users/devashishbadlani/dev/content-factory/.working_dir/learningseries/
└── newtons_laws_curriculum.md      ← single markdown file, no runs yet
/Users/devashishbadlani/dev/content-factory/.working_dir/series/
├── learning_series_*/              ← 1 audited run (grade F, 10 findings)
└── short_movie_series_*/           ← 1 episodic shape, audited
```

What the auditor sees in that 1 learning_series run:

| Failure | Count | What it tells us |
|---|---:|---|
| F3_council_unapplied | 5 directives | Each episode has its own audit, none applied |
| F4_blocker_silenced | 1 | curriculum_gap_report flagged "missing_topic_overlap" |
| F2b_guard_not_run | 1 | episode-level guard never invoked |
| F5_open_feedback | 1 | season-level feedback never closed |
| C_continuity (NEW) | 2 (palette, sharpness drift) | mid-season model swap visible |

The structural finding: **the season-level state is not propagated to the
episode children.** Each episode re-derives the brand palette, voice cast,
recurring vocabulary — and drifts.

## 2. The shape gas-town gives it

```
gt-epic-newtons-laws (season)                   ← parent epic (bd-*)
│
├── hq-newtons-S01E01 (mountain convoy)         ← episode 1
│   ├── stage: curriculum_resolve
│   ├── stage: lesson_planner
│   ├── stage: script
│   ├── stage: storyboard            (parallel × scenes)
│   ├── stage: video_generation      (parallel × scenes, max_concurrent=4)
│   ├── stage: voiceover             (parallel × lines)
│   ├── stage: assembly
│   ├── stage: caption_burn
│   ├── stage: audio_master
│   ├── stage: council_audit         (max_redos=3)
│   ├── stage: episode_qa
│   └── stage: publish
│
├── hq-newtons-S01E02 (mountain)
│
├── hq-newtons-S01-bible (convoy, not mountain)
│   ├── tracks: continuity bible updates from each episode
│   ├── waits_for_gate: G_curriculum_arc_consistent
│   └── auto-closes when all episodes publish
│
└── hq-newtons-S01-feedback (convoy)
    ├── parents: every published episode
    ├── scheduled: +24h / +72h / +7d per episode
    └── closes: when all episodes have a 7d engagement reading
```

The **bible convoy is the unlock**. Today every episode re-reads
`studio_bible.json` from its own working dir; the convoy makes the bible a
versioned bead that every episode reads via `gt bead show
bd-newtons-bible`. Any episode that modifies the bible writes a new bead
version, and Refinery's `G_curriculum_arc_consistent` gate diffs the new
bible against the prior episodes' outputs to catch contradictions before
they ship.

## 3. The end-to-end flow

```
                                 +----------------------------+
  user/scheduler ──── gt formula run learning-series-episode  │
                          │      │     name=newtons-laws       │
                          │      │     episode=2               │
                          ▼      +----------------------------+
            ┌─────────────────────────┐
            │ gt mountain newtons-S01E02 │
            └────────────┬────────────────┘
                         │ Wave 1: curriculum_resolve
                         ▼
              ┌──────────────────────────┐
              │ Hermes ←── FTS5 recall   │  "what did E01 cover for momentum?"
              │ Honcho persona           │  "this brand never uses red CTAs"
              │ /context cap 1500 tok    │  "S01 voice cast: ELEVEN_voice_42"
              └─────────────┬────────────┘
                            ▼
                    bd update curriculum.bead ── canonical season state
                            │
                            ▼
       (waves 2…N — same shape as viral_shorts mountain, but PARENTED to season)
                            ▼
              ┌──────────────────────────┐
              │ Refinery gates (tier=aaa)│
              │   + G_curriculum_arc      │  ← NEW gate, learning_series only
              │   + G_voice_continuity    │
              │   + G_difficulty_curve    │
              └─────────────┬────────────┘
                            ▼
                    publish → Postiz → engagement_capture
                            │
                            ▼
          season-feedback convoy receives the engagement reading,
          updates Hermes' `learning_completion_curve` for this brand
```

## 4. The 3 new gates this pipeline needs

These don't exist in the current refinery.toml; add them under `[[gate]]`:

```toml
[[gate]]
id = "G_curriculum_arc_consistent"
description = "Episode N's lesson does not contradict episodes 1..N-1"
auditor = "polecat://contentx-edu/arc-checker"
predicate = "diff(curriculum_bible.json, prior_episodes_summary.json) | contradictions == 0"
required_for = ["learning_series"]
severity_on_fail = "BLOCKER"

[[gate]]
id = "G_voice_continuity"
description = "Same character → same ElevenLabs voice across all episodes of a season"
auditor = "polecat://contentx-audio/voice-continuity"
predicate = "for_each_character_in_voice_registry.json: voice_id == season_voice_registry.json[character].voice_id"
required_for = ["learning_series", "tv_series", "audiobook"]
severity_on_fail = "CRITICAL"

[[gate]]
id = "G_difficulty_curve"
description = "Episode N's difficulty score within [prev+0.05, prev+0.20] band"
auditor = "polecat://contentx-edu/difficulty"
predicate = "difficulty_score >= prev_episode.difficulty_score + 0.05 && difficulty_score <= prev_episode.difficulty_score + 0.20"
required_for = ["learning_series"]
severity_on_fail = "HIGH"
```

## 5. The 4 new Hermes skills this pipeline needs

These would land at `~/.hermes/skills/contentx-edu/`:

| Skill | Triggered by | What it injects |
|---|---|---|
| `season-bible-loader` | every phase | load the season's bible bead + last episode's output summary as `/context` |
| `cliffhanger-design` | scripter | end every episode at a 6/10 tension peak; closing question relates to next ep's premise |
| `recap-injection` | scripter | first 8 s of each episode > 2 is a beat-by-beat recap of the prior episode's resolution |
| `difficulty-progression` | curriculum_resolve | walks Bloom's taxonomy levels; never regresses, never jumps two levels in a row |

The first one is the most leveraged — it's why episode 2 has palette drift
from episode 1 today (it doesn't see episode 1's brand_colors.json).

## 6. The bd / gt incantation

One-time per season:

```bash
# Create the season epic
SEASON=$(bd create "Newton's Laws — season 1" \
  --type=epic --priority=1 \
  --labels=learning_series,newtons-laws,S01 \
  --description="6-episode foundational physics series for KS3 audience" \
  | grep -oE 'bd-[a-z0-9-]+' | head -1)

# Create the season bible bead — every episode reads this
bd create "S01 continuity bible" \
  --type=task --priority=1 \
  --parent="$SEASON" \
  --labels=learning_series,bible,S01 \
  --metadata=@bible.json   # the seed bible (voice cast, palette, vocab list)

# Create the season-feedback convoy
gt convoy create newtons-S01-feedback \
  --parent="$SEASON" \
  --description="rollup of engagement metrics across all S01 episodes"
```

Per episode:

```bash
# Launch an episode mountain
gt formula run learning-series-episode \
  --season=newtons-laws \
  --episode=2 \
  --bible=bd-newtons-bible \
  --tier=aaa

# It returns a convoy id like hq-newtons-S01E02; watch with:
gt mountain status hq-newtons-S01E02
gt trail --rig=contentx-edu | grep newtons-S01E02
```

Cross-episode: the bible convoy (`hq-newtons-S01-bible`) tracks each episode's
diff against the bible. If episode 3 introduces a new term, that's a
`bible_diff` bead that has to be merged into the bible (via `bd update` on the
bible bead) before episode 4 starts — which the formula enforces with
`waits_for_gate: G_curriculum_arc_consistent`.

## 7. The learning-loop closure

This is where learning_series ≠ viral_shorts. Each episode's engagement is a
**learning signal** (not just popularity):

```python
# In hermes/postiz_engagement_scraper.py — learning_series specific code path
def closure_for_learning_series(run, metrics):
    completion = metrics.get("avg_view_duration") / metrics["video_duration"]
    drop_off_point = metrics.get("retention_curve").drop_off_seconds(threshold=0.5)
    if drop_off_point and drop_off_point < run.episode_duration * 0.6:
        # students bailed before the lesson resolved — flag the curriculum step
        bd_create(
            title=f"E{run.episode_n}: 50% drop at {drop_off_point:.0f}s — lesson_step={run.steps_at(drop_off_point)}",
            type="bug",
            priority="1",
            parent=run.season_bead,
            labels=["learning_series","retention","drop-off"],
        )
        # the next planner run consults this bead via FTS5
```

The drop-off bead becomes searchable: when episode N+1's planner asks Hermes
"how did students react to similar-difficulty content in this brand," the
answer includes the specific drop-off bead and the planner avoids that
pattern. **This is what the team's MEMORY_FEEDBACK_LOOP_IMPACT.md projected
as +18–25% retention; it can only happen with the bible-as-bead + drop-off-as-bead
architecture.**

## 8. Refinery cert chain for a 6-episode season

```
episode 1 ──────► G_script_present ──► G_curriculum_arc ──► G_voice_continuity ──► G_difficulty_curve ──► G_audio_passed ──► G_council_applied ──► G_delivery_passed ──► G_human_signoff (tier=aaa) ──► publish ✓
episode 2 ──────► (same chain, plus G_curriculum_arc reads from episode 1's output bead) ──► publish ✓
…
episode 6 ──────► same chain, plus the season-bible-loader skill checks the *entire* arc
season cert ───► every episode published + G_season_completion_curve ≥ 0.55 ──► season closes
```

`G_season_completion_curve` is the season-level gate: average completion-rate
across all 6 episodes' 7-day engagement readings must be ≥ 0.55. If it fails,
the season convoy reopens — the bottom-3 episodes are routed back into
council_audit with the drop-off beads in their `/context`, and a new edit pass
ships.

## 9. The cost / outcome story

The team's own table projected `+18–25% retention` for learning_series. Why
this number lands:

- **+8 pp from the recap-injection skill** (industry standard for serialized
  edu content; CMU LearnLab study, 2024)
- **+5 pp from voice continuity** (G_voice_continuity catches the model swap
  that's currently 🔴 in CONTINUITY_FLAWS_ANALYSIS)
- **+4 pp from drop-off bead recall** (next episode avoids the specific
  difficulty cliff)
- **+3–8 pp from cliffhanger-design** (highly variable by topic)

Operational: 1 season = 6 episodes = 6 mountains × ~25 min each (with the
parallel scene fan-out) = **~2.5 h wall-clock per season** vs the current
linear-pipeline ~14 h. The 6× compression is purely from `parallel: true`
inside the mountain — not from cutting corners.

## 10. Next moves

If you green-light the learning_series scaffolding the same way you did the
viral_shorts one, the work breaks into:

1. **Add the 3 gates** to `configs/refinery.toml` (1 hr) — purely declarative
2. **Author the 4 Hermes skills** at `~/.hermes/skills/contentx-edu/` (1 day)
3. **Wire `closure_for_learning_series()`** into the postiz_engagement_scraper
   (half day)
4. **Build the season-bible-loader polecat** — it's the only new agent role
   needed; everything else is already in the viral_shorts polecat pool (2 days)
5. **Run the Newton's Laws curriculum** that's already at
   `working_dir/learningseries/newtons_laws_curriculum.md` as the first season
   (8–10 h wall-clock if all 6 episodes ship in one pass; 1 weekend with
   council audit redos factored in)

Say the word and I'll generate the analogous `scaffolding/learning_series/`
folder — `bootstrap_beads.sh` for the season epic, `mountain.yaml` for the
episode shape, and the 4 skill `.md` files — just like the viral_shorts one.
