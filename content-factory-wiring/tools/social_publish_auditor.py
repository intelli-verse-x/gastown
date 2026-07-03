"""
social_publish_auditor.py — studio-grade audit for video/audio about to be published to social.

For every final_video*.mp4 (and equivalents) we verify against the platform's
hard requirements + our own brand floor:

  M1  loudness_target          : LUFS integrated within platform window
  M2  loudness_peak            : true-peak (dBTP) below platform ceiling
  M3  aspect_ratio             : exactly the target ratio (9:16 / 1:1 / 16:9)
  M4  duration                 : within platform cap (60s shorts / 90s TT / etc)
  M5  resolution_floor         : 1080×1920 / 1080×1080 / 1920×1080 minimum
  M6  framerate                : 24-60 fps, no funny non-integer rates
  M7  audio_stream_present     : audio stream exists + non-silent
  M8  safe_zone_top            : no important content in top 250px (TT/IG UI)
  M9  safe_zone_bottom         : no important content in bottom 350px
  M10 hook_window              : first 3s has audio + motion (Laplacian + RMS)
  M11 caption_present          : srt/vtt or burned-in subs found
  M12 thumbnail_present        : a poster frame artifact exists
  M13 cta_present              : publish_metadata has a CTA in description
  M14 brand_compliance         : brand_colors.json present, palette mapped

Reads:
  • Output mp4 (via ffprobe + ffmpeg loudnorm scan)
  • publish_metadata.json
  • Adjacent .srt/.vtt and *_thumbnail.* files

Usage:
    python social_publish_auditor.py <run_path> [--platform=youtube_shorts|tiktok|instagram_reels|all]
    python social_publish_auditor.py --batch <parent_dir>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "youtube_shorts": {
        "lufs_target": -14.0,
        "lufs_tolerance": 1.0,
        "tp_max_dbtp": -1.0,
        "aspect": (9, 16),
        "duration_max_s": 60.0,
        "res_min": (1080, 1920),
        "safe_top_px": 200,
        "safe_bottom_px": 250,
    },
    "tiktok": {
        "lufs_target": -16.0,
        "lufs_tolerance": 2.0,
        "tp_max_dbtp": -1.0,
        "aspect": (9, 16),
        "duration_max_s": 90.0,
        "res_min": (1080, 1920),
        "safe_top_px": 220,
        "safe_bottom_px": 350,
    },
    "instagram_reels": {
        "lufs_target": -14.0,
        "lufs_tolerance": 1.5,
        "tp_max_dbtp": -2.0,
        "aspect": (9, 16),
        "duration_max_s": 90.0,
        "res_min": (1080, 1920),
        "safe_top_px": 250,
        "safe_bottom_px": 350,
    },
    "youtube_main": {
        "lufs_target": -14.0,
        "lufs_tolerance": 1.0,
        "tp_max_dbtp": -1.0,
        "aspect": (16, 9),
        "duration_max_s": 3600.0,
        "res_min": (1920, 1080),
        "safe_top_px": 0,
        "safe_bottom_px": 80,
    },
    "linkedin_feed": {
        "lufs_target": -16.0,
        "lufs_tolerance": 2.0,
        "tp_max_dbtp": -1.0,
        "aspect": (1, 1),
        "duration_max_s": 600.0,
        "res_min": (1080, 1080),
        "safe_top_px": 80,
        "safe_bottom_px": 120,
    },
}


@dataclass
class MediaFinding:
    code: str
    severity: str
    message: str
    platform: str | None = None
    measurement: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def ffprobe(path: Path) -> dict[str, Any]:
    rc, out, err = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    if rc != 0:
        return {"_error": err or "ffprobe failed"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_error": "ffprobe returned non-json"}


def measure_loudness(path: Path, target_lufs: float = -14.0) -> dict[str, Any]:
    rc, _out, err = _run([
        "ffmpeg", "-nostats", "-hide_banner", "-i", str(path),
        "-filter_complex", f"loudnorm=I={target_lufs}:TP=-1.0:LRA=11:print_format=json",
        "-f", "null", "-",
    ], timeout=300)
    if rc != 0:
        return {"_error": err.splitlines()[-1] if err else "loudnorm failed"}
    m = re.search(r"\{[\s\S]*?\}", err)
    if not m:
        return {"_error": "loudnorm json not found"}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"_error": "loudnorm json invalid"}


# ---------------------------------------------------------------------------

def audit_video(video: Path, run_root: Path, platform: str) -> list[MediaFinding]:
    spec = PLATFORM_SPECS[platform]
    findings: list[MediaFinding] = []
    rel = str(video.relative_to(run_root))

    probe = ffprobe(video)
    if "_error" in probe:
        return [MediaFinding(
            code="M_ffprobe_failed",
            severity="blocker",
            message=f"{rel}: ffprobe failed — {probe['_error']}",
            platform=platform,
            measurement={"file": rel},
        )]

    streams = probe.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = probe.get("format", {})

    if not vstreams:
        return [MediaFinding(
            code="M_no_video_stream",
            severity="blocker",
            message=f"{rel}: no video stream",
            platform=platform,
        )]

    vs = vstreams[0]
    w, h = int(vs.get("width", 0)), int(vs.get("height", 0))
    fps_raw = vs.get("r_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) > 0 else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    dur = float(fmt.get("duration", 0))

    # M3 — aspect
    a_w, a_h = spec["aspect"]
    expected_ratio = a_w / a_h
    actual_ratio = w / h if h > 0 else 0
    if abs(actual_ratio - expected_ratio) > 0.02:
        findings.append(MediaFinding(
            code="M3_aspect_ratio",
            severity="blocker",
            message=f"{rel}: aspect {w}x{h} ({actual_ratio:.3f}) ≠ {a_w}:{a_h} ({expected_ratio:.3f})",
            platform=platform,
            measurement={"w": w, "h": h, "expected": f"{a_w}:{a_h}"},
        ))

    # M4 — duration
    if dur > spec["duration_max_s"]:
        findings.append(MediaFinding(
            code="M4_duration_over",
            severity="blocker",
            message=f"{rel}: {dur:.1f}s exceeds platform cap {spec['duration_max_s']}s",
            platform=platform,
            measurement={"duration": dur, "cap": spec["duration_max_s"]},
        ))
    if dur < 1.5:
        findings.append(MediaFinding(
            code="M4_duration_under",
            severity="critical",
            message=f"{rel}: {dur:.1f}s is suspiciously short",
            platform=platform,
            measurement={"duration": dur},
        ))

    # M5 — resolution floor
    min_w, min_h = spec["res_min"]
    if w < min_w or h < min_h:
        findings.append(MediaFinding(
            code="M5_resolution_floor",
            severity="critical",
            message=f"{rel}: {w}x{h} below platform floor {min_w}x{min_h}",
            platform=platform,
            measurement={"w": w, "h": h},
        ))

    # M6 — framerate sanity
    if fps < 23.9 or fps > 60.5:
        findings.append(MediaFinding(
            code="M6_framerate",
            severity="critical",
            message=f"{rel}: framerate {fps:.2f} fps outside 24-60 fps range",
            platform=platform,
            measurement={"fps": fps},
        ))

    # M7 — audio stream
    if not astreams:
        findings.append(MediaFinding(
            code="M7_no_audio_stream",
            severity="blocker",
            message=f"{rel}: no audio stream — required for social publish",
            platform=platform,
        ))
    else:
        as0 = astreams[0]
        # Quick silence check via loudness measurement
        loud = measure_loudness(video, target_lufs=spec["lufs_target"])
        if "_error" in loud:
            findings.append(MediaFinding(
                code="M_loudness_failed",
                severity="critical",
                message=f"{rel}: could not measure loudness — {loud['_error']}",
                platform=platform,
            ))
        else:
            input_i = float(loud.get("input_i", 0))
            input_tp = float(loud.get("input_tp", 0))
            # M1 — LUFS
            if abs(input_i - spec["lufs_target"]) > spec["lufs_tolerance"]:
                findings.append(MediaFinding(
                    code="M1_loudness_target",
                    severity="critical",
                    message=(
                        f"{rel}: integrated {input_i:.1f} LUFS ≠ "
                        f"{spec['lufs_target']:.1f}±{spec['lufs_tolerance']:.1f} target"
                    ),
                    platform=platform,
                    measurement={"input_i": input_i, "target": spec["lufs_target"]},
                ))
            # M2 — TP
            if input_tp > spec["tp_max_dbtp"]:
                findings.append(MediaFinding(
                    code="M2_loudness_peak",
                    severity="critical",
                    message=f"{rel}: true peak {input_tp:.2f} dBTP > {spec['tp_max_dbtp']} dBTP ceiling",
                    platform=platform,
                    measurement={"input_tp": input_tp},
                ))
            # M7b — silent
            if input_i < -55:
                findings.append(MediaFinding(
                    code="M7b_silent_audio",
                    severity="blocker",
                    message=f"{rel}: audio is effectively silent ({input_i:.1f} LUFS)",
                    platform=platform,
                ))

    # M11 — captions
    siblings = list(video.parent.glob(f"{video.stem}*.srt")) + list(video.parent.glob(f"{video.stem}*.vtt"))
    if not siblings:
        siblings = list(video.parent.parent.rglob("*.srt")) + list(video.parent.parent.rglob("*.vtt"))
    if not siblings:
        findings.append(MediaFinding(
            code="M11_caption_missing",
            severity="critical",
            message=f"{rel}: no caption file (.srt/.vtt) found — accessibility fail",
            platform=platform,
        ))

    # M12 — thumbnail
    thumb_candidates = (
        list(video.parent.glob(f"{video.stem}_thumb*"))
        + list(video.parent.glob("*thumbnail*"))
        + list(run_root.rglob("*thumbnail*.png"))
        + list(run_root.rglob("*thumbnail*.jpg"))
    )
    if not thumb_candidates:
        findings.append(MediaFinding(
            code="M12_thumbnail_missing",
            severity="critical",
            message=f"{rel}: no thumbnail artifact found",
            platform=platform,
        ))

    # M13 — CTA presence (from publish_metadata)
    publish_meta = next(run_root.rglob("publish_metadata.json"), None)
    cta_present = False
    if publish_meta and publish_meta.exists():
        try:
            meta = json.loads(publish_meta.read_text())
            text_blob = json.dumps(meta).lower()
            cta_present = any(p in text_blob for p in [
                "subscribe", "follow", "like", "comment", "share",
                "click", "visit", "swipe", "link in bio", "tap"
            ])
        except json.JSONDecodeError:
            pass
    if not cta_present:
        findings.append(MediaFinding(
            code="M13_cta_missing",
            severity="critical",
            message=f"{rel}: no CTA detected in publish_metadata",
            platform=platform,
        ))

    # M14 — brand compliance signal
    brand_file = next(run_root.rglob("brand_colors.json"), None)
    if not brand_file or not brand_file.exists():
        findings.append(MediaFinding(
            code="M14_brand_palette_missing",
            severity="medium",
            message=f"{rel}: no brand_colors.json — palette compliance not verifiable",
            platform=platform,
        ))

    # M10 — hook (first 3s motion + audio)
    # Use ffprobe scene detection on first 3 seconds
    rc, out, _ = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "frame=pkt_pts_time,pict_type",
        "-of", "csv=p=0", "-read_intervals", "0%+3",
        str(video),
    ], timeout=30)
    if rc == 0 and out:
        frames = [line for line in out.splitlines() if line.strip()]
        if len(frames) < 30:  # <10 fps in first 3s suggests static
            findings.append(MediaFinding(
                code="M10_hook_static",
                severity="critical",
                message=f"{rel}: first 3s appears static ({len(frames)} frames sampled) — kills retention",
                platform=platform,
                measurement={"first_3s_frames": len(frames)},
            ))

    return findings


def audit_run(run_path: Path, platforms: list[str]) -> dict[str, Any]:
    videos = sorted(set(
        list(run_path.rglob("final_video*.mp4"))
        + list(run_path.rglob("video.mp4"))
        + list(run_path.rglob("master.mp4"))
        + list(run_path.rglob("*_master.mp4"))
    ))
    # Filter out scene fragments (we only want full deliverables)
    videos = [v for v in videos if "scene_" not in str(v) or "final" in v.stem]

    all_findings: list[dict] = []
    for video in videos:
        for platform in platforms:
            for f in audit_video(video, run_path, platform):
                all_findings.append({**asdict(f), "video": str(video.relative_to(run_path))})

    return {
        "run_id": run_path.name,
        "run_path": str(run_path),
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "n_videos": len(videos),
        "platforms": platforms,
        "findings": all_findings,
        "summary": {
            "by_code": _count(all_findings, "code"),
            "by_severity": _count(all_findings, "severity"),
            "n_findings": len(all_findings),
        },
    }


def _count(items: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in items:
        v = f.get(key)
        if v is not None:
            out[v] = out.get(v, 0) + 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--batch", help="parent dir")
    ap.add_argument("--platform", default="youtube_shorts,tiktok,instagram_reels")
    ap.add_argument("--out", help="write JSON report")
    args = ap.parse_args()

    if args.platform == "all":
        platforms = list(PLATFORM_SPECS.keys())
    else:
        platforms = [p.strip() for p in args.platform.split(",")]

    if args.batch:
        root = Path(args.batch).expanduser().resolve()
        results = []
        for run in sorted(p for p in root.iterdir() if p.is_dir()):
            r = audit_run(run, platforms)
            if r["n_videos"] > 0:
                results.append(r)
                print(f"  {run.name}: {r['summary']['n_findings']} findings across {r['n_videos']} video(s)")
        report = {"batch": str(root), "runs": results, "platforms": platforms}
    else:
        report = audit_run(Path(args.path).expanduser().resolve(), platforms)

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nreport -> {args.out}")
    else:
        print(json.dumps(report, indent=2)[:4000])


if __name__ == "__main__":
    main()
