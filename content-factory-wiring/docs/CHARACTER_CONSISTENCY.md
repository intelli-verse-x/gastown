# Character Consistency Across Pipelines

**Goal:** every face / character / voice in every shot of every pipeline maps back to a single registered identity, with multi-character scenes verifying *each* character independently.

## The four levels

```
┌─────────────────────────────────────────────────────────────────────┐
│ L4  Cross-pipeline reuse          (registry shared everywhere)      │ G15 + canon
├─────────────────────────────────────────────────────────────────────┤
│ L3  Multi-character integrity     (all declared chars present)      │ G15 (CC9)
├─────────────────────────────────────────────────────────────────────┤
│ L2  Per-character canonical match (face / outfit / voice → canon)   │ G15 (CC3/6/7/8)
├─────────────────────────────────────────────────────────────────────┤
│ L1  Adjacent-shot continuity      (shot n vs shot n+1)              │ G4
└─────────────────────────────────────────────────────────────────────┘
```

Each pipeline must satisfy every level its tier requires.

## The registry

Single source of truth at `${CONTENTX_CHARACTER_REGISTRY:-/var/lib/content-factory/character_registry/}`:

```
character_registry/
├── registry.json                       # index (locked, type, voice_id, tags)
├── chain_of_custody.jsonl              # every mutation HMAC-signed
└── <char_id>/
    ├── canonical.json                  # name, type, outfit_states, lock state
    ├── face_embeddings.npz             # face bank (1-N reference embeddings)
    ├── voice_embedding.npz             # speaker embedding
    └── outfits/<state>.json            # per-outfit detail + color histogram
```

The same `quizzy` directory is referenced by `viral_shorts`, `learning_series`, `ads`, and `movies`. There is exactly one canonical Quizzy.

## The per-run cast manifest

Every pipeline writes **before any render** to `cast/cast_manifest.json`:

```json
{
  "version": "1.0",
  "scenes": [
    {
      "scene_id": "scene_03",
      "characters": [
        { "char_id": "quizzy",   "expected_outfit": "default",   "frame_share_min": 0.10 },
        { "char_id": "narrator", "expected_outfit": "voice_only","frame_share_min": 0.00 }
      ]
    }
  ],
  "signature": "<hmac-sha256>"
}
```

The signature is the same HMAC primitive as the studio gates. Tampering invalidates the manifest and G15 blocks.

## G15 — what it blocks on

| Code | Meaning | Why |
|---|---|---|
| `CC1_cast_manifest_missing` | no `cast/cast_manifest.json` | pipeline didn't declare cast → audit impossible |
| `CC2_cast_unknown_character` | cast names a `char_id` not in registry | someone fabricated a character; must register first |
| `CC3_unregistered_face_detected` | detected face matches no declared character | "ghost" — a model hallucinated a person |
| `CC4_declared_character_missing` | required character (frame_share_min > 0) never appears | scene fails its own brief |
| `CC5_identity_swap` | face matches the wrong declared character | scene 5 Quizzy is actually NewQuizzy by accident |
| `CC6_identity_drift_from_canonical` | face cosine-distance to canonical bank > tier threshold | render quality slipped; character looks off |
| `CC7_outfit_drift` | torso HSV histogram drifts from declared outfit state | declared lab_coat, rendered with hoodie |
| `CC8_voice_drift` | speaker embedding cosine-distance from canonical voice > tier threshold | TTS regressed or wrong voice_id used |
| `CC9_multi_character_misalignment` | declared 2+ required chars, fewer detected | the "lone Quizzy" failure mode for ensemble shots |

## Per-pipeline integration

Every pipeline's planner must add **two write steps** to its generate phase:

```python
# pipelines/viral_shorts/planner.py (example)
from tools.character_consistency.registry import CharacterRegistry

registry = CharacterRegistry()

# 1. resolve declared cast against the registry (fail-fast)
for ch in declared_cast:
    if not registry.exists(ch.char_id):
        raise PipelineError(f"unregistered character: {ch.char_id}")

# 2. write the manifest before rendering anything
cast_path = run_path / "cast" / "cast_manifest.json"
cast_path.parent.mkdir(exist_ok=True)
manifest = {"version": "1.0", "scenes": [...]}
manifest["signature"] = sign(manifest)
cast_path.write_text(json.dumps(manifest, indent=2))
```

Then any time the renderer produces a new shot, the existing G15 + refinery loop will:
1. Sample frames from the shot
2. Detect every face (insightface → face_recognition → phash)
3. Embed each face, compare to the declared cast's reference banks
4. Block or pass per the tier policy in `policies/character_consistency_policy.toml`

## Per-pipeline-kind expectations

| Pipeline | Default tier | Strict multi-char? | Voice match? | Min refs |
|---|---|---|---|---|
| `viral_shorts` | indie | off | off | 1 |
| `ads` | aa+ | on | on | 10 |
| `learning_series` | aa+ | on (recurring instructor) | on | 8 |
| `movies` | aaa+ | on (ensemble) | on | 12 |
| `podcast_series` | aa | n/a (no face) | on | 6 |

Overrides live in `policies/character_consistency_policy.toml` and are loaded by the cron-driven `gt refinery reload`.

## Backend selection — automatic, with graceful degradation

```
preferred  ──►  insightface buffalo_l  (EER ≈ 0.20, ~99.8% LFW)
fallback 1 ──►  face_recognition       (EER ≈ 0.28, ~99.4% LFW)
fallback 2 ──►  phash                  (EER ≈ 0.39 — advisory only)
```

The bootstrap script `deploy/02_bootstrap_host.sh` installs `face_recognition` opportunistically. For tier ≥ AAA we want `insightface` — install via:

```bash
pip install insightface onnxruntime
```

Voice backends:
```
preferred  ──►  resemblyzer    (cosine threshold 0.30)
fallback   ──►  13-bin MFCC    (cosine threshold 0.45, advisory)
```

## Lock semantics — canon-controlled mutation

Characters can be **locked** by the Creative Director:

```bash
python -m tools.character_consistency.registry lock quizzy --by "C. Director" --hours 720
```

While locked, any pipeline rendering against Quizzy is required to:
1. Use only outfit_states present at lock time
2. Have G15 distance ≤ tier threshold to the existing face bank
3. Not add new face references without an `unlock` event

Unlocking is recorded in `chain_of_custody.jsonl` with the reason. G2 (canon_lock) treats character-level locks the same way it treats series-bible locks.

## Audit trail — every event signed, every event auditable

Every registry mutation appends to `character_registry/chain_of_custody.jsonl`. Every G15 run appends a signed entry to the per-run `chain_of_custody.jsonl`. These two streams are independently mirrored to `s3://contentx-audit-cold/` per the 7y retention policy.

## Verification

`tools/studio_gates/post_deploy_verify.py` exercises G15 against `fixtures/known_good_run` (which contains a tiny seeded `character_registry/` + `cast/cast_manifest.json`) and against `known_bad_run` (which has neither — G15 must block).

```bash
CONTENTX_CERT_KEY=... python tools/studio_gates/post_deploy_verify.py   # 12/12
CONTENTX_CERT_KEY=... python tools/validate_bundle.py                   # 28/28
```
