"""G11 Localization — per-locale captions, voice cast, lip-sync window.

For every locale declared in run.json.locales OR locales/ subdirs:
  L1 caption_per_locale     — locales/<lang>/captions.{srt,vtt} present
  L2 audio_per_locale       — locales/<lang>/audio.{wav,mp3} present
  L3 voice_cast_per_locale  — locale voice_cast.json names a voice in the locale's language
  L4 cultural_review_marker — locales/<lang>/cultural_review.json with verdict ∈ {APPROVED}
  L5 lipsync_window         — abs(audio_duration - video_duration) <= 250ms
  L6 ui_string_completeness — every ui_strings.json key present in every locale
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from . import GateFinding, GateResult, now_utc, sign
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign  # type: ignore


def _safe_json(p: Path) -> Any:
    try: return json.loads(p.read_text())
    except Exception: return None


def _audio_duration(p: Path) -> float | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    run_meta = _safe_json(run_path / "run.json") or {}
    declared = set(run_meta.get("locales") or [])
    locales_dir = run_path / "locales"
    if locales_dir.is_dir():
        declared |= {p.name for p in locales_dir.iterdir() if p.is_dir()}

    if not declared:
        # No locales declared → no localization gate needed
        return _result(
            [], run_path, tier,
            passed=True,
        )

    # Source-language video duration (for L5)
    src_video = next(run_path.rglob("final_video*.mp4"), None) or next(run_path.rglob("video.mp4"), None)
    src_duration = _audio_duration(src_video) if src_video else None

    for loc in sorted(declared):
        loc_dir = locales_dir / loc
        if not loc_dir.exists():
            findings.append(GateFinding(
                code="L0_locale_dir_missing",
                severity="blocker",
                message=f"locale `{loc}` declared but locales/{loc}/ does not exist",
                measurement={"locale": loc},
            ))
            continue

        # L1 caption
        if not (list(loc_dir.glob("*.srt")) or list(loc_dir.glob("*.vtt"))):
            findings.append(GateFinding(
                code="L1_caption_per_locale_missing",
                severity="blocker",
                message=f"locale {loc}: no .srt/.vtt",
                measurement={"locale": loc},
            ))

        # L2 audio
        audio_files = list(loc_dir.glob("*.wav")) + list(loc_dir.glob("*.mp3")) + list(loc_dir.glob("*.m4a"))
        if not audio_files:
            findings.append(GateFinding(
                code="L2_audio_per_locale_missing",
                severity="critical",
                message=f"locale {loc}: no audio dub file",
                measurement={"locale": loc},
            ))

        # L3 voice cast
        vc = loc_dir / "voice_cast.json"
        if vc.exists():
            data = _safe_json(vc) or {}
            lang_codes = data.get("language_code"), data.get("locale")
            if loc not in str(lang_codes) and not data.get("voices"):
                findings.append(GateFinding(
                    code="L3_voice_cast_locale_mismatch",
                    severity="critical",
                    message=f"locale {loc}: voice_cast.json missing voices/language match",
                    measurement={"locale": loc},
                ))
        else:
            findings.append(GateFinding(
                code="L3_voice_cast_missing",
                severity="critical",
                message=f"locale {loc}: voice_cast.json absent",
                measurement={"locale": loc},
            ))

        # L4 cultural review
        cr = loc_dir / "cultural_review.json"
        if cr.exists():
            data = _safe_json(cr) or {}
            verdict = (data.get("verdict") or "").upper()
            if verdict != "APPROVED":
                findings.append(GateFinding(
                    code="L4_cultural_review_not_approved",
                    severity="blocker",
                    message=f"locale {loc}: cultural_review verdict={verdict}",
                    measurement={"locale": loc, "verdict": verdict},
                ))
        else:
            findings.append(GateFinding(
                code="L4_cultural_review_missing",
                severity="blocker",
                message=f"locale {loc}: cultural_review.json absent",
                measurement={"locale": loc},
            ))

        # L5 lip-sync window
        if src_duration and audio_files:
            d_loc = _audio_duration(audio_files[0])
            if d_loc and abs(d_loc - src_duration) > 0.250:
                findings.append(GateFinding(
                    code="L5_lipsync_window_exceeded",
                    severity="critical",
                    message=(
                        f"locale {loc}: audio {d_loc:.2f}s vs source {src_duration:.2f}s "
                        f"(delta {abs(d_loc-src_duration)*1000:.0f}ms > 250ms)"
                    ),
                    measurement={"locale": loc, "audio_s": d_loc, "source_s": src_duration},
                ))

    # L6 UI string completeness (if ui_strings present)
    src_ui = next(run_path.rglob("ui_strings.json"), None)
    if src_ui:
        src = _safe_json(src_ui) or {}
        src_keys = set(src.keys()) if isinstance(src, dict) else set()
        for loc in declared:
            loc_ui = (locales_dir / loc / "ui_strings.json")
            if loc_ui.exists():
                data = _safe_json(loc_ui) or {}
                missing = src_keys - set(data.keys() if isinstance(data, dict) else [])
                if missing:
                    findings.append(GateFinding(
                        code="L6_ui_keys_missing",
                        severity="major",
                        message=f"locale {loc}: {len(missing)} ui_strings keys missing",
                        measurement={"locale": loc, "missing": sorted(missing)[:10]},
                    ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G11", gate_name="localization", passed=passed, tier=tier,
        findings=findings, run_id=run_path.name, evaluated_at=now_utc(),
    )
    r.signature = sign(r.to_dict())
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_path")
    ap.add_argument("--tier", default="aaa")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = evaluate(Path(args.run_path).expanduser().resolve(), args.tier)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
    else:
        print(f"[G11 localization] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
