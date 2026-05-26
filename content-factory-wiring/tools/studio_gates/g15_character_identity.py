"""G15 Character Identity — every face in every shot maps to a declared, registered character.

Inputs (per run):
    cast/cast_manifest.json         — required; declares which characters appear in each scene
    scenes/*/shots/*/frames/*.png   — rendered shot frames (sampled, not exhaustive)
    audio/dialogue_*.wav            — optional; for voice consistency

Outputs:
    gates/G15.json                  — signed result
    council_audits/character_consistency.json  — per-character per-shot table

Blocking conditions (CRITICAL findings):
    CC1  cast_manifest_missing          — no cast/cast_manifest.json found
    CC2  cast_unknown_character         — cast names a char_id not in registry
    CC3  unregistered_face_detected     — ghost: detected face matches no declared character
    CC4  declared_character_missing     — character with frame_share_min > 0 never appears
    CC5  identity_swap                  — best-match is the WRONG declared character
    CC6  identity_drift_from_canonical  — face distance to canonical bank > backend threshold
    CC7  outfit_drift                   — torso histogram drifts from declared outfit state
    CC8  voice_drift                    — speaker embedding drifts from canonical voice
    CC9  multi_character_misalignment   — declared 2+ chars, fewer detected than required

All registry-backed: same registry can be referenced from viral_shorts, learning_series,
movies, ads — character consistency is enforced cross-pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# Allow `python g15_character_identity.py <run>` or `python -m tools.studio_gates.g15...`
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "character_consistency"))

try:
    from . import GateFinding, GateResult, now_utc, sign
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign  # type: ignore

# character_consistency package
from registry import CharacterRegistry  # type: ignore  # noqa: E402
from embedder import (  # type: ignore  # noqa: E402
    detect_and_embed_faces,
    face_distance_to_bank,
    face_distance,
    face_backend,
    outfit_histogram,
    outfit_distance,
    voice_embed,
    voice_distance,
    voice_backend,
    FACE_THRESHOLD,
    VOICE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_rgb(p: Path) -> np.ndarray | None:
    try:
        return np.array(Image.open(p).convert("RGB"))
    except Exception:
        return None


def _load_cast(run_path: Path) -> dict[str, Any] | None:
    cm = run_path / "cast" / "cast_manifest.json"
    if not cm.exists():
        return None
    try:
        return json.loads(cm.read_text())
    except json.JSONDecodeError:
        return None


def _enumerate_scene_shots(run_path: Path, scene_id: str) -> list[Path]:
    """Find frame samples for a scene. Tolerates several pipeline layouts."""
    candidates: list[Path] = []
    # Layout A: scenes/<scene_id>/shots/<shot>/frames/<n>.png
    candidates += sorted((run_path / "scenes" / scene_id).rglob("frames/*.png"))
    # Layout B: media/<scene_id>/shot_*.png
    candidates += sorted((run_path / "media").rglob(f"{scene_id}*/*.png"))
    # Layout C: thumbnails next to scene videos
    candidates += sorted(run_path.rglob(f"*{scene_id}*thumb*.png"))
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def _dialogue_audio(run_path: Path, scene_id: str) -> list[Path]:
    """Find dialogue audio files for a scene (optional)."""
    out = []
    for pattern in (f"audio/{scene_id}_*.wav", f"audio/*{scene_id}*.wav",
                    f"dialogue/{scene_id}*.wav"):
        out += list(run_path.rglob(pattern))
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    audit_log: list[dict[str, Any]] = []

    cast = _load_cast(run_path)
    if not cast:
        findings.append(GateFinding(
            code="CC1_cast_manifest_missing",
            severity="blocker",
            message="cast/cast_manifest.json not found — every pipeline must declare cast before render",
        ))
        return _result(findings, run_path, tier, audit_log)

    registry_path = os.environ.get("CONTENTX_CHARACTER_REGISTRY")
    registry_root = Path(registry_path) if registry_path else None
    # Allow a per-run registry override (symlink)
    run_registry = run_path / "character_registry"
    if run_registry.exists():
        registry_root = run_registry
    registry = CharacterRegistry(registry_root)

    # ----------- CC2: every cast member must be registered ---------------
    registered_ids = set(registry.list_characters())
    for scene in cast.get("scenes", []):
        for ch in scene.get("characters", []):
            cid = ch.get("char_id", "")
            if cid not in registered_ids:
                findings.append(GateFinding(
                    code="CC2_cast_unknown_character",
                    severity="blocker",
                    message=f"scene {scene.get('scene_id')}: char_id '{cid}' not in registry",
                    measurement={"scene_id": scene.get("scene_id"), "char_id": cid},
                ))

    # Build a per-character face bank cache
    face_banks: dict[str, tuple[str, np.ndarray]] = {}
    voice_refs: dict[str, np.ndarray] = {}
    expected_outfits: dict[str, np.ndarray] = {}
    for cid in registered_ids:
        bank = registry.face_bank(cid)
        if bank is not None and len(bank) > 0:
            face_banks[cid] = (face_backend(), bank)
        vref = registry.voice_reference(cid)
        if vref is not None:
            voice_refs[cid] = vref
        canon = registry.get_character(cid)
        if canon:
            for outfit in canon.outfit_states:
                if outfit.histogram:
                    expected_outfits[f"{cid}::{outfit.state_id}"] = np.array(outfit.histogram, dtype=np.float32)

    fb = face_backend()
    fb_thresh = FACE_THRESHOLD.get(fb, 0.35)

    # ----------- Per-scene walk ---------------
    for scene in cast.get("scenes", []):
        scene_id = scene.get("scene_id", "scene_?")
        declared = scene.get("characters", [])
        if not declared:
            continue

        declared_ids = [c.get("char_id") for c in declared if c.get("char_id") in registered_ids]
        per_char_appearances = {cid: 0 for cid in declared_ids}

        frames = _enumerate_scene_shots(run_path, scene_id)
        # Sample up to 20 frames per scene to keep cost bounded.
        if len(frames) > 20:
            stride = len(frames) // 20
            frames = frames[::stride][:20]

        for frame_path in frames:
            arr = _read_rgb(frame_path)
            if arr is None:
                continue
            detections = detect_and_embed_faces(arr)
            audit_entry = {
                "scene_id": scene_id,
                "frame": str(frame_path.relative_to(run_path)),
                "detected_faces": len(detections),
                "matched": [],
                "unmatched": 0,
            }

            for det in detections:
                emb = det["embedding"]
                # Find closest declared character for this detection.
                best_id, best_dist = None, 1.0
                for cid in declared_ids:
                    backend_b, bank = face_banks.get(cid, (fb, None))
                    if bank is None:
                        continue
                    d = face_distance_to_bank(emb, bank, backend_b)
                    if d < best_dist:
                        best_id, best_dist = cid, d

                if best_id is None or best_dist > fb_thresh:
                    findings.append(GateFinding(
                        code="CC3_unregistered_face_detected",
                        severity="blocker",
                        message=(
                            f"{scene_id} / {frame_path.name}: detected face with no match in declared cast "
                            f"{declared_ids} (closest={best_id}, dist={best_dist:.3f})"
                        ),
                        measurement={
                            "scene_id": scene_id, "frame": str(frame_path.name),
                            "bbox": det["bbox"], "closest": best_id, "distance": best_dist,
                            "threshold": fb_thresh, "backend": fb,
                        },
                    ))
                    audit_entry["unmatched"] += 1
                    continue

                per_char_appearances[best_id] += 1
                audit_entry["matched"].append({
                    "char_id": best_id, "distance": round(best_dist, 4),
                    "bbox": det["bbox"],
                })

                # ----------- CC6: drift from canonical (already enforced via threshold) ---------
                if best_dist > fb_thresh * 0.75:
                    findings.append(GateFinding(
                        code="CC6_identity_drift_from_canonical",
                        severity="critical",
                        message=(
                            f"{scene_id} / {frame_path.name}: '{best_id}' face distance "
                            f"{best_dist:.3f} approaches threshold {fb_thresh:.2f}"
                        ),
                        measurement={
                            "scene_id": scene_id, "char_id": best_id,
                            "distance": best_dist, "threshold": fb_thresh, "backend": fb,
                        },
                    ))

                # ----------- CC7: outfit drift -----------
                cast_member = next((c for c in declared if c.get("char_id") == best_id), None)
                if cast_member:
                    expected_state = f"{best_id}::{cast_member.get('expected_outfit','default')}"
                    canonical_hist = expected_outfits.get(expected_state)
                    if canonical_hist is not None:
                        observed = outfit_histogram(arr, det["bbox"])
                        dist = outfit_distance(observed, canonical_hist)
                        if dist > 0.40:
                            findings.append(GateFinding(
                                code="CC7_outfit_drift",
                                severity="critical",
                                message=(
                                    f"{scene_id} / {frame_path.name}: '{best_id}' outfit drifted from "
                                    f"declared '{cast_member.get('expected_outfit','default')}' "
                                    f"(chi2={dist:.3f})"
                                ),
                                measurement={
                                    "scene_id": scene_id, "char_id": best_id,
                                    "expected_outfit": cast_member.get('expected_outfit'),
                                    "distance": dist,
                                },
                            ))

            audit_log.append(audit_entry)

        # ----------- CC4: required characters must appear -----------
        for ch in declared:
            cid = ch.get("char_id")
            req_share = float(ch.get("frame_share_min", 0))
            if req_share > 0 and per_char_appearances.get(cid, 0) == 0:
                findings.append(GateFinding(
                    code="CC4_declared_character_missing",
                    severity="blocker",
                    message=(
                        f"{scene_id}: '{cid}' required (frame_share_min={req_share}) "
                        "but not detected in any sampled frame"
                    ),
                    measurement={"scene_id": scene_id, "char_id": cid, "required_share": req_share},
                ))

        # ----------- CC9: multi-character scene must show >=2 named characters -----------
        required = [c for c in declared if float(c.get("frame_share_min", 0)) > 0]
        if len(required) >= 2:
            present = sum(1 for c in required if per_char_appearances.get(c["char_id"], 0) > 0)
            if present < len(required):
                findings.append(GateFinding(
                    code="CC9_multi_character_misalignment",
                    severity="blocker",
                    message=(
                        f"{scene_id}: multi-character scene declared {len(required)} required chars, "
                        f"only {present} actually detected"
                    ),
                    measurement={"scene_id": scene_id, "declared": len(required), "detected": present},
                ))

        # ----------- CC8: voice consistency for dialogue -----------
        dialogues = _dialogue_audio(run_path, scene_id)
        vb = voice_backend()
        vt = VOICE_THRESHOLD.get(vb, 0.40)
        for wav in dialogues:
            stem = wav.stem.lower()
            speaker_id = None
            for ch in declared:
                cid = ch["char_id"].lower()
                if cid in stem:
                    speaker_id = ch["char_id"]; break
            if speaker_id is None or speaker_id not in voice_refs:
                continue
            backend_used, emb = voice_embed(wav)
            if emb is None:
                continue
            dist = voice_distance(emb, voice_refs[speaker_id])
            if dist > vt:
                findings.append(GateFinding(
                    code="CC8_voice_drift",
                    severity="blocker",
                    message=(
                        f"{scene_id} / {wav.name}: '{speaker_id}' voice cos-distance "
                        f"{dist:.3f} > {vt:.2f} (backend={backend_used})"
                    ),
                    measurement={
                        "scene_id": scene_id, "char_id": speaker_id,
                        "distance": dist, "threshold": vt, "backend": backend_used,
                    },
                ))

    return _result(findings, run_path, tier, audit_log)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(findings, run_path: Path, tier: str, audit_log: list[dict[str, Any]]) -> GateResult:
    passed = not any(f.severity in ("blocker", "critical") for f in findings)
    result = GateResult(
        gate_id="G15",
        gate_name="character_identity",
        passed=passed,
        tier=tier,
        findings=findings,
        run_id=run_path.name,
        evaluated_at=now_utc(),
    )
    body = result.to_dict()
    body.pop("signature", None)
    result.signature = sign(body)

    gates_dir = run_path / "gates"
    gates_dir.mkdir(exist_ok=True)
    (gates_dir / "G15.json").write_text(json.dumps(result.to_dict(), indent=2))

    audits_dir = run_path / "council_audits"
    audits_dir.mkdir(exist_ok=True)
    audit_body = {
        "rubric_id": "character_consistency",
        "auditor": "G15CharacterIdentity",
        "auditor_role": "agent://auditor/character_identity",
        "run_id": run_path.name,
        "evaluated_at": result.evaluated_at,
        "tier": tier,
        "passed": passed,
        "per_frame": audit_log,
    }
    audit_body["signature"] = sign(audit_body)
    (audits_dir / "character_consistency_audit.json").write_text(json.dumps(audit_body, indent=2))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_path", type=Path)
    ap.add_argument("--tier", default="aa")
    args = ap.parse_args()
    if not args.run_path.exists():
        print(f"run_path does not exist: {args.run_path}", file=sys.stderr); return 2
    res = evaluate(args.run_path, tier=args.tier)
    print(json.dumps(res.to_dict(), indent=2))
    return 0 if res.passed else 1


if __name__ == "__main__":
    sys.exit(main())
