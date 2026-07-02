"""Build the known_good_run fixture.

Run once after cloning to regenerate signed approvals + chain-of-custody:
    CONTENTX_CERT_KEY=... python fixtures/build_fixtures.py

The known_bad_run is just `run.json` and intentionally needs no setup.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools" / "studio_gates"))

# Ensure a deterministic key if caller forgot to export one (for CI repeatability)
os.environ.setdefault("CONTENTX_CERT_KEY", "fixture-key-only-not-for-production-pass-2026-AAAA")

from __init__ import sign, now_utc  # type: ignore  # noqa: E402
from g14_chain_of_custody import append as coc_append  # type: ignore  # noqa: E402
from g13_dual_signoff import sign_for  # type: ignore  # noqa: E402

import numpy as np

GOOD = HERE / "known_good_run"


def _seed_character_registry(run_path: Path) -> None:
    """Create a minimal in-run character registry so G15 can exercise."""
    sys.path.insert(0, str(ROOT / "tools" / "character_consistency"))
    from registry import CharacterRegistry  # type: ignore  # noqa: E402
    from _models import OutfitState  # type: ignore  # noqa: E402

    reg = CharacterRegistry(run_path / "character_registry")
    if reg.exists("quizzy"):
        return
    # Two outfit states with deterministic 12-bin HSV histograms.
    default_hist = [0.18,0.10,0.08,0.07,0.06,0.06,0.07,0.08,0.08,0.07,0.07,0.08]
    lab_hist     = [0.05,0.05,0.05,0.20,0.20,0.15,0.10,0.05,0.05,0.04,0.03,0.03]
    canon = reg.create_character(
        char_id="quizzy",
        name="Quizzy",
        char_type="animated_2d",
        voice_id="quizzy_v3",
        tags=["brand:quizverse"],
        outfit_states=[
            OutfitState(state_id="default", description="standard purple visor",
                        primary_colors=["#7c4dff", "#f3a712"], histogram=default_hist),
            OutfitState(state_id="lab_coat", description="white coat halloween_2026",
                        primary_colors=["#ffffff", "#22d3ee"], histogram=lab_hist),
        ],
    )
    # Seed face bank with a deterministic dummy embedding (phash-shape so the
    # phash fallback path also passes without an ML backend installed).
    bank_emb = np.array([1.0] * 64, dtype=np.float32)
    reg.add_face_reference("quizzy", bank_emb, backend="phash", source="fixture")
    # Add a 13-dim MFCC-lite reference
    voice_emb = np.array([0.5] * 13, dtype=np.float32)
    voice_emb /= np.linalg.norm(voice_emb)
    reg.add_voice_reference("quizzy", voice_emb, backend="mfcc", source="fixture")


def _write_cast_manifest(run_path: Path) -> None:
    cast_dir = run_path / "cast"
    cast_dir.mkdir(exist_ok=True)
    manifest = {
        "version": "1.0",
        "scenes": [
            {
                "scene_id": "scene_01",
                "characters": [
                    {
                        "char_id": "quizzy",
                        "expected_outfit": "default",
                        "expected_state": "neutral",
                        "voice_id": "quizzy_v3",
                        "frame_share_min": 0.0,
                    },
                ],
            },
        ],
    }
    manifest["signature"] = sign(manifest)
    (cast_dir / "cast_manifest.json").write_text(json.dumps(manifest, indent=2))


def main() -> int:
    # Reset everything except run.json
    keep = {"run.json"}
    if GOOD.exists():
        for child in GOOD.iterdir():
            if child.name not in keep:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

    GOOD.mkdir(parents=True, exist_ok=True)

    # ---------------- G1 concept_lock ----------------
    (GOOD / "metadata").mkdir(exist_ok=True)
    pitch_content = {
        "title": "Quizzy demo short",
        "premise": "a cheerful know-it-all who teaches one fact per video",
        "audience": "gen-z trivia",
        "tone": "warm, snappy, curious",
    }
    pitch_hash = hashlib.sha256(
        json.dumps(pitch_content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    pitch = dict(pitch_content, hash=pitch_hash, approvals={})
    for role in ("creative_director", "technical_director"):
        payload = {
            "role": role,
            "signer": f"Fixture {role}",
            "signed_at": now_utc(),
            "pitch_hash": pitch_hash,
        }
        payload["signature"] = sign(payload)
        pitch["approvals"][role] = payload
    (GOOD / "metadata" / "pitch_deck.json").write_text(json.dumps(pitch, indent=2))

    # ---------------- G2 canon_lock ----------------
    canon = {
        "characters": [
            {"id": "quizzy", "name": "Quizzy", "visor": True, "voice": "warm-bright"},
        ],
        "palette": ["#7c4dff", "#f3a712", "#22d3ee"],
        "props": ["quiz_card", "buzzer"],
        "vocabulary": {"banned": [], "preferred": ["did you know"]},
    }
    canon_hash = hashlib.sha256(
        json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    bible = dict(canon, lock={
        "locked": True,
        "content_hash": canon_hash,
        "frozen_at": now_utc(),
    })
    (GOOD / "studio_bible.json").write_text(json.dumps(bible, indent=2))

    # ---------------- G3 script_multi_read ----------------
    (GOOD / "scripts").mkdir(exist_ok=True)
    (GOOD / "scripts" / "story.txt").write_text(
        "Did you know one tiny habit beats every trivia trick? "
        "Comment your guess to find out tomorrow."
    )
    # Creative read (R1)
    (GOOD / "council_audits").mkdir(exist_ok=True)
    (GOOD / "council_audits" / "screenwriting_audit.json").write_text(json.dumps({
        "final_verdict": "APPROVED",
        "directives": [],
        "redo_count": 0,
        "max_redos": 0,
    }, indent=2))

    # ---------------- G6 rights_manifest ----------------
    rights = {
        "assets": {
            "output/final_video.mp4": {
                "type": "video",
                "source": "fixture-placeholder",
                "model": "n/a",
                "seed": None,
                "license": "AI-generated-proprietary",
                "license_url": "https://contentx/fixture",
                "consent": None,
                "clearance_status": "cleared",
                "expires_at": None,
            },
            "output/final_video.srt": {
                "type": "video",
                "source": "fixture-placeholder",
                "model": "n/a",
                "seed": None,
                "license": "AI-generated-proprietary",
                "license_url": "https://contentx/fixture",
                "consent": None,
                "clearance_status": "cleared",
                "expires_at": None,
            },
        },
        "_note": "Fixture rights for the placeholder output files.",
    }
    (GOOD / "rights_manifest.json").write_text(json.dumps(rights, indent=2))

    # ---------------- G10 council_enforcer ----------------
    (GOOD / "council_audits" / "video_audit.json").write_text(json.dumps({
        "final_verdict": "APPROVED",
        "directives": [],
        "redo_count": 0,
        "max_redos": 0,
        "overall_score": 7.4,
    }, indent=2))

    # ---------------- G5/G8 external (social_publish_auditor) ----------------
    (GOOD / "social_publish_audit.json").write_text(json.dumps({
        "summary": {"by_severity": {"blocker": 0, "critical": 0, "high": 0}},
        "_note": "Fixture: no video present, audit shape only.",
    }, indent=2))

    # ---------------- Output placeholder (so output_hash covers something) ----
    (GOOD / "output").mkdir(exist_ok=True)
    (GOOD / "output" / "final_video.mp4").write_bytes(b"\x00FAKE_MP4_FIXTURE\x00")
    (GOOD / "output" / "final_video.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\nDid you know one tiny habit beats every trivia trick?\n"
    )

    # ---------------- G14 chain_of_custody ----------------
    coc_append(GOOD, {"kind": "fixture_built"})
    (GOOD / "retention.json").write_text(json.dumps({
        "years": 7,
        "created_at": now_utc(),
        "policy_source": "fixture",
    }, indent=2))

    # ---------------- G13 dual_signoff (optional for indie; useful for tier=aa)  ----
    (GOOD / "approvals").mkdir(exist_ok=True)
    sign_for(GOOD, "creative_director", "Fixture CD")
    sign_for(GOOD, "technical_director", "Fixture TD")

    # ---------------- G15 character_identity ------------------------------
    _seed_character_registry(GOOD)
    _write_cast_manifest(GOOD)

    print(f"known_good_run rebuilt at {GOOD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
