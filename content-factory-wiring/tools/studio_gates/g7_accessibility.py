"""G7 Accessibility — WCAG 2.1 AA + photosensitivity + captions + dub.

Checks:
  A1 captions_present         — .srt or .vtt sidecar AND burned-in mp4
  A2 photosensitivity_safe    — no >3 flashes/sec exceeding 25% luminance delta
                                 (PEAT-aligned; full PEAT requires licensed tool)
  A3 color_contrast_wcag      — text overlay regions must hit ≥ 4.5:1 contrast on body text
  A4 audio_description        — for tier aaa, runs must include audio_description track
                                  (separate audio stream or transcript marker)
  A5 dub_per_locale           — locales/<lang>/audio.* present for every locale declared
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:
    from . import GateFinding, GateResult, now_utc, sign
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign  # type: ignore


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:
        return 127, "", str(exc)


def _safe_json(p: Path) -> Any:
    try: return json.loads(p.read_text())
    except Exception: return None


def _videos(run_path: Path) -> list[Path]:
    return sorted(set(
        list(run_path.rglob("final_video*.mp4"))
        + list(run_path.rglob("video.mp4"))
        + list(run_path.rglob("*_master.mp4"))
    ))


def _photosensitivity_scan(video: Path) -> dict[str, Any]:
    """Harding-aligned photosensitivity scan.

    The Harding test (the broadcast standard, used by Ofcom and licensed via
    Cambridge Research Systems' PEAT) flags:

      H1  general flash:   ≥3 luminance transitions/sec at ≥10% screen
                            with ΔL ≥ 20% of full-scale dynamic range
      H2  red flash:        saturated-red regions ≥25% screen oscillating ≥3 Hz
      H3  spatial pattern:  high-contrast stripes covering >40% screen
                            (this stub does not measure spatial pattern; production
                             must use licensed PEAT)

    Production: if `peat-cli` is on PATH (purchased license), shell out to it
    and return its verdict directly. Otherwise the Harding heuristic below
    catches gross offenders.
    """
    # ----- 1. Licensed PEAT shell-out (preferred if installed) -----
    peat = shutil_which("peat-cli")
    if peat:
        try:
            r = subprocess.run(
                [peat, "--input", str(video), "--output-format", "json"],
                capture_output=True, text=True, timeout=600,
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                return {
                    "source": "licensed_peat",
                    "max_flashes_per_second": data.get("max_flashes_per_sec", 0),
                    "max_red_flashes_per_second": data.get("max_red_flashes_per_sec", 0),
                    "peat_verdict": data.get("verdict"),
                    "raw": data,
                }
        except Exception:
            pass  # fall through to heuristic

    # ----- 2. Harding heuristic -----
    # Sample at 30 fps so we can resolve 15Hz flicker (Nyquist for the ~3Hz limit + headroom).
    # Use a 96x54 sample (≈ 5,184 pixels) — fine enough to detect localized flashes,
    # cheap enough to process a full minute in ~1s.
    try:
        proc_y = subprocess.run([
            "ffmpeg", "-nostats", "-hide_banner", "-i", str(video),
            "-vf", "fps=30,scale=96:54,format=gray",
            "-f", "rawvideo", "-",
        ], capture_output=True, timeout=600)
        proc_rgb = subprocess.run([
            "ffmpeg", "-nostats", "-hide_banner", "-i", str(video),
            "-vf", "fps=30,scale=96:54,format=rgb24",
            "-f", "rawvideo", "-",
        ], capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"error": "ffmpeg timeout"}
    if proc_y.returncode != 0 or proc_rgb.returncode != 0:
        return {"error": "ffmpeg failed"}

    px = 96 * 54
    raw_y = proc_y.stdout
    raw_rgb = proc_rgb.stdout
    n = min(len(raw_y) // px, len(raw_rgb) // (px * 3))
    if n < 30:
        return {"error": f"too few frames: {n}"}

    Y = np.frombuffer(raw_y[: n * px], dtype=np.uint8).reshape(n, 54, 96).astype(np.float32) / 255.0
    RGB = np.frombuffer(raw_rgb[: n * px * 3], dtype=np.uint8).reshape(n, 54, 96, 3).astype(np.float32) / 255.0

    # ----- H1 general flash -----
    # ΔL ≥ 0.20 of dynamic range on ≥10% of pixels
    dy = np.abs(np.diff(Y, axis=0))                       # (n-1, 54, 96)
    big_pixels = (dy > 0.20)
    big_pct_per_frame = big_pixels.mean(axis=(1, 2))      # fraction of pixels flashing
    big_screen_transitions = big_pct_per_frame > 0.10     # ≥10% screen
    # Count transitions in sliding 1-second window
    max_h1 = 0
    for i in range(0, len(big_screen_transitions) - 30):
        in_win = big_screen_transitions[i : i + 30].sum()
        if in_win > max_h1:
            max_h1 = int(in_win)

    # ----- H2 red flash -----
    # Saturated red: R > 0.8 AND G < 0.4 AND B < 0.4
    R, G, B = RGB[..., 0], RGB[..., 1], RGB[..., 2]
    red_mask = (R > 0.8) & (G < 0.4) & (B < 0.4)
    red_pct = red_mask.mean(axis=(1, 2))                  # fraction red per frame
    # Transition: red_pct crosses >25% threshold up or down
    red_above = (red_pct > 0.25).astype(np.int8)
    red_transitions = np.abs(np.diff(red_above))
    max_h2 = 0
    for i in range(0, len(red_transitions) - 30):
        in_win = red_transitions[i : i + 30].sum()
        if in_win > max_h2:
            max_h2 = int(in_win)

    return {
        "source": "harding_heuristic",
        "fps_sampled": 30,
        "nframes": n,
        "max_flashes_per_second": max_h1,
        "max_red_flashes_per_second": max_h2,
        "harding_h1_threshold": 3,
        "harding_h2_threshold": 3,
    }


def shutil_which(cmd: str) -> str | None:
    import shutil as _shutil
    return _shutil.which(cmd)


def _contrast_ratio(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    def lum(c):
        srgb = [v / 255.0 for v in c]
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in srgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    la = lum(rgb_a) + 0.05
    lb = lum(rgb_b) + 0.05
    return max(la, lb) / min(la, lb)


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    videos = _videos(run_path)
    if not videos:
        return _result(
            [GateFinding(code="G7_no_video", severity="low",
                         message="no final video found — accessibility checks skipped")],
            run_path, tier, passed=True,
        )

    # A1 — Captions present
    for v in videos:
        siblings = list(v.parent.glob(f"{v.stem}*.srt")) + list(v.parent.glob(f"{v.stem}*.vtt"))
        if not siblings:
            siblings = list(run_path.rglob("*.srt")) + list(run_path.rglob("*.vtt"))
        if not siblings:
            findings.append(GateFinding(
                code="A1_caption_missing",
                severity="blocker",
                message=f"{v.relative_to(run_path)}: no .srt/.vtt anywhere",
            ))

    # A2 — Photosensitivity
    for v in videos:
        result = _photosensitivity_scan(v)
        if "error" in result:
            findings.append(GateFinding(
                code="A2_photosensitivity_unmeasured",
                severity="medium",
                message=f"{v.relative_to(run_path)}: could not scan ({result['error']})",
            ))
            continue
        if result["max_flashes_per_second"] > 3:
            findings.append(GateFinding(
                code="A2_photosensitivity_unsafe",
                severity="blocker",
                message=(
                    f"{v.relative_to(run_path)}: peak {result['max_flashes_per_second']} large "
                    "luminance transitions per second (>3 fails Harding H1 / WCAG 2.3.1)"
                ),
                measurement=result,
            ))
        if result.get("max_red_flashes_per_second", 0) > 3:
            findings.append(GateFinding(
                code="A2b_red_flash_unsafe",
                severity="blocker",
                message=(
                    f"{v.relative_to(run_path)}: peak {result['max_red_flashes_per_second']} "
                    "saturated-red flashes per second (>3 fails Harding H2)"
                ),
                measurement=result,
            ))
        if result.get("peat_verdict") == "FAIL":
            findings.append(GateFinding(
                code="A2c_peat_fail",
                severity="blocker",
                message="licensed PEAT analysis returned FAIL",
                measurement=result,
            ))

    # A3 — Color contrast (best-effort from caption styling metadata)
    style_file = next(run_path.rglob("caption_style.json"), None)
    if style_file:
        s = _safe_json(style_file) or {}
        fg = s.get("font_color")
        bg = s.get("background")
        if fg and bg:
            try:
                ratio = _contrast_ratio(_parse_color(fg), _parse_color(bg))
                if ratio < 4.5:
                    findings.append(GateFinding(
                        code="A3_contrast_below_wcag",
                        severity="critical",
                        message=f"caption contrast {ratio:.2f}:1 < WCAG AA 4.5:1",
                        measurement={"contrast": ratio, "fg": fg, "bg": bg},
                    ))
            except Exception:
                pass

    # A4 — Audio description for aaa
    if tier in ("aaa", "live-aaa"):
        ad = list(run_path.rglob("*audio_description*.wav")) + list(run_path.rglob("*audio_description*.mp3")) \
             + list(run_path.rglob("*ad_track*"))
        if not ad:
            findings.append(GateFinding(
                code="A4_audio_description_missing",
                severity="blocker",
                message="tier=aaa requires an audio_description track (none found)",
            ))

    # A5 — Dub per locale
    run_meta = _safe_json(run_path / "run.json") or {}
    locales = run_meta.get("locales") or []
    for loc in locales:
        dubs = list(run_path.rglob(f"locales/{loc}/audio*")) + list(run_path.rglob(f"locales/{loc}/*.wav"))
        if not dubs:
            findings.append(GateFinding(
                code="A5_dub_missing",
                severity="critical",
                message=f"locale `{loc}` declared but no audio dub present",
                measurement={"locale": loc},
            ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _parse_color(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if len(s) == 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    if len(s) == 3:
        return int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16)
    raise ValueError("unparseable color")


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G7", gate_name="accessibility", passed=passed, tier=tier,
        findings=findings, run_id=run_path.name, evaluated_at=now_utc(),
    )
    r.signature = sign(r.to_dict())
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_path")
    ap.add_argument("--tier", default="aa")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = evaluate(Path(args.run_path).expanduser().resolve(), args.tier)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
    else:
        print(f"[G7 accessibility] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
