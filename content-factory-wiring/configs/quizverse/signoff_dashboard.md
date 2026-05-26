# QuizVerse Asset Cert — Sign-off Dashboard

**Generated:** auto from `/tmp/quizverse-audit/reports/audit_report.json`
**Status:** Quizzy DEMO READY for sign-off. 14 characters queued behind it.

## The decision in front of you

Sign off on Quizzy's fix recipe. Everything else flows.

### Quizzy proof-of-fix

| Metric | Before | After | Delta |
|---|---|---|---|
| Total flaws | 23 | 6 | **−17** |
| Blockers | 9 | 0 | **−9** |
| Critical | 13 | 0 | **−13** |
| Weighted defect score | 157 | 12 | **−145 (92%)** |

**Recipe applied:**
1. `rembg u2netp` on 9 opaque emotion views → all now alpha
2. Base views normalized to 1024×1536 canvas
3. 6 separate animation sheets → 1 master atlas (3082×3082, Unity-ready)
4. Master atlas JSON conforms to manifest's `unity_sprite_requirements`

**Residual (non-blocking at Tier-2):** 6 frames with Laplacian variance below 30
(pixelation) — requires regeneration at higher source resolution. Tracked as
separate bead `qv-quizzy-regen` for Tier-3 promotion later.

**Artifacts to inspect:**
- `comparisons/quizzy_01_transparency.png` — opaque BG → alpha
- `comparisons/quizzy_02_master_atlas.png` — 6 files → 1 file
- `fixed/Quizzy/sprites/quizzy_master_atlas.png` — Unity-importable
- `fixed/Quizzy/sprites/quizzy_master_atlas.json` — sprite spec

---

## Other characters — what the audit revealed (manifest said "fixed")

### AUTOcurio — 21 flaws (BLOCKERS the manifest hid)
- `attack_spritesheet.png` is **2928×352, ZERO opaque pixels** — completely empty
- `hurt_spritesheet.png` is **2064×512, ZERO opaque pixels** — completely empty
- 13 pixelation flaws across remaining sheets
- 3 sprite-sheets with 30-99% bbox drift between frames

### Bear — 7 flaws
- 3 sheets with frame drift (attack 42%, hurt 39%, walk 34%)
- Missing transparency on one variant
- Pivot inconsistency on idle

### Quizzy variants (v1, v2) — not yet audited, projected ~18 each from pattern
### Atlas, Dog, Duck, Echo, IX, Luna, Nova, Pixel, Professor, Sparky — not yet audited
  (Mountain convoy stage 1 will audit all 11 in parallel in ~3 minutes)

---

## How to sign off

### Option A — One-click approval (Tier-2 / AA)
You eyeball the two comparison images above. If happy:
```bash
bd close qv-quizzy --comment "Recipe approved. Apply to remaining 14."
gt mountain start quizverse-art-cert-redelivery
```
Witness then runs the mountain convoy autonomously, pinging you on Telegram only when
human sign-off is needed (Stage 5) for each character.

### Option B — Per-character review (Tier-3 / AAA)
Same as above but `gt mountain start ... --human-approve-per-character`.

### Option C — Reject
```bash
bd update qv-quizzy --status=needs_changes --comment "<your notes>"
```
Recipe gets revised before any of the 14 are touched.

---

## What gas-town will do for the 14

1. **Audit** all in parallel (~3 min)
2. **Fix** them in batches of 4 (~12 min total wall clock)
3. **Re-audit** each (~3 min parallel)
4. **Build comparisons** for each (~3 min parallel)
5. **Telegram dispatch** to you, one at a time, with thumbnail + score delta
6. **Sign cert files** + **republish to S3** under `agent-assets/games/quiz-verse/cert/<char>/`

Estimated wall clock for all 14: **~30 min auto + your sign-off time**.

If any character can't reach 80% defect reduction with the recipe (e.g. AUTOcurio's
empty sheets need regeneration, not transparency fixing), the polecat escalates:
`gt escalate --severity=HIGH --route=mayor "<char> needs regeneration, not patching"`.

That bead then routes to the generation polecat in a *separate* convoy, never blocking the others.
