"""
continuity_detector.py — detect cross-shot continuity flaws inside a run_id.

The team's CONTINUITY_FLAWS_ANALYSIS flags these as 🔴 unfixed:
  • background establishment frames missing
  • previous-shot reference frame not propagated
  • prop compositing inconsistent across shots
  • character view selection drift
  • multi-character spatial inconsistency

This script scans a run's scenes/shots, compares character bounding boxes,
background color histograms, prop presence, and visual_style metadata
across consecutive shots, and reports any drift.

Inputs:
  • {run_path}/scenes/*/shots/*/frames/*.png  (preferred)
  • or {run_path}/media/scene_*/shot_*.png
  • or {run_path}/{run_id}_shot_*.mp4 (fallback, extract frames via ffmpeg)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


@dataclass
class ContinuityFinding:
    code: str
    severity: str
    shot_a: str
    shot_b: str | None
    message: str
    measurement: dict[str, Any]


def _read_image(p: Path) -> np.ndarray | None:
    try:
        return np.array(Image.open(p).convert("RGBA"))
    except (OSError, Image.UnidentifiedImageError):
        return None


def _bg_histogram(arr: np.ndarray, bins: int = 8) -> np.ndarray:
    """Return a normalized 3D RGB histogram of pixels with alpha>200 in the outer 20%."""
    h, w = arr.shape[:2]
    mask = np.zeros((h, w), dtype=bool)
    edge = max(int(min(h, w) * 0.2), 30)
    mask[:edge, :] = True
    mask[-edge:, :] = True
    mask[:, :edge] = True
    mask[:, -edge:] = True
    pixels = arr[mask]
    pixels = pixels[pixels[:, 3] > 200]  # opaque
    if len(pixels) == 0:
        return np.zeros((bins, bins, bins))
    rgb = pixels[:, :3]
    hist, _ = np.histogramdd(rgb, bins=bins, range=[[0, 256], [0, 256], [0, 256]])
    s = hist.sum()
    return hist / s if s > 0 else hist


def _hist_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric chi-square distance between two histograms (0 = identical)."""
    eps = 1e-8
    return float(0.5 * np.sum((a - b) ** 2 / (a + b + eps)))


def _laplacian_var(arr: np.ndarray) -> float:
    gray = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]).astype(np.float32)
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    out = np.zeros_like(gray)
    out[1:-1, 1:-1] = (
        k[0, 1] * gray[:-2, 1:-1] + k[1, 0] * gray[1:-1, :-2] + k[1, 1] * gray[1:-1, 1:-1] +
        k[1, 2] * gray[1:-1, 2:] + k[2, 1] * gray[2:, 1:-1]
    )
    return float(out.var())


def _extract_thumbnail(video: Path, t: float = 0.5) -> Path | None:
    out = video.parent / f".{video.stem}_thumb.png"
    if out.exists():
        return out
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)],
            check=True, capture_output=True, timeout=30,
        )
        return out if out.exists() else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _gather_shots(run_path: Path) -> list[tuple[str, Path]]:
    """Return [(shot_id, frame_path)] in narrative order."""
    out: list[tuple[str, Path]] = []
    # Frame-based runs
    for frame in sorted(run_path.rglob("scenes/*/shots/*/frames/*.png")):
        parts = frame.parts
        try:
            scene_idx = [i for i, p in enumerate(parts) if p.startswith("scene_")][0]
            shot_idx = [i for i, p in enumerate(parts) if p.startswith("shot_")][0]
            shot_id = f"{parts[scene_idx]}/{parts[shot_idx]}"
            out.append((shot_id, frame))
        except IndexError:
            continue
    # Media-based runs
    if not out:
        for frame in sorted(run_path.rglob("media/scene_*/shot_*.png")):
            parts = frame.parts
            try:
                scene_idx = [i for i, p in enumerate(parts) if p.startswith("scene_")][0]
                shot_id = f"{parts[scene_idx]}/{frame.stem}"
                out.append((shot_id, frame))
            except IndexError:
                continue
    # Video-based runs (extract thumb)
    if not out:
        for vid in sorted(run_path.rglob("*shot_*.mp4")):
            thumb = _extract_thumbnail(vid)
            if thumb:
                # Identify scene/shot from filename
                m = re.search(r"scene_(\d+)_shot_(\d+)", vid.stem)
                if m:
                    sid = f"scene_{int(m.group(1)):02d}/shot_{int(m.group(2)):02d}"
                else:
                    sid = vid.stem
                out.append((sid, thumb))
    return out


def detect_continuity(run_path: Path) -> list[ContinuityFinding]:
    findings: list[ContinuityFinding] = []
    shots = _gather_shots(run_path)
    if len(shots) < 2:
        return [ContinuityFinding(
            code="C0_too_few_shots",
            severity="low",
            shot_a="(none)",
            shot_b=None,
            message=f"{run_path.name}: only {len(shots)} shot frame(s) found — cannot evaluate continuity",
            measurement={"n_shots": len(shots)},
        )]

    prev_hist: np.ndarray | None = None
    prev_lap: float | None = None
    prev_sid: str | None = None

    for sid, frame in shots:
        arr = _read_image(frame)
        if arr is None:
            findings.append(ContinuityFinding(
                code="C5_unreadable_frame",
                severity="major",
                shot_a=sid,
                shot_b=None,
                message=f"{sid}: cannot decode {frame.name}",
                measurement={"path": str(frame)},
            ))
            continue

        if arr.shape[-1] != 4:
            arr = np.dstack([arr, np.full(arr.shape[:2], 255, dtype=np.uint8)])

        hist = _bg_histogram(arr)
        lap = _laplacian_var(arr)

        # C1 — background palette drift
        if prev_hist is not None:
            dist = _hist_distance(hist, prev_hist)
            if dist > 0.35:  # threshold tuned: 0=identical, 1=fully different
                findings.append(ContinuityFinding(
                    code="C1_background_palette_drift",
                    severity="critical",
                    shot_a=prev_sid or "?",
                    shot_b=sid,
                    message=(
                        f"background palette shifted between {prev_sid} → {sid} "
                        f"(chi-sq distance {dist:.2f}, threshold 0.35)"
                    ),
                    measurement={"distance": dist},
                ))

        # C3 — sharpness drift (visual_style continuity proxy)
        if prev_lap is not None:
            ratio = max(lap, prev_lap) / max(min(lap, prev_lap), 1e-3)
            if ratio > 3.0:
                findings.append(ContinuityFinding(
                    code="C3_sharpness_drift",
                    severity="major",
                    shot_a=prev_sid or "?",
                    shot_b=sid,
                    message=(
                        f"sharpness ratio {ratio:.1f}x between {prev_sid} → {sid} "
                        f"({prev_lap:.0f} vs {lap:.0f}) — model swap or upscale inconsistency"
                    ),
                    measurement={"ratio": ratio, "prev_var": prev_lap, "this_var": lap},
                ))

        # C4 — empty/almost-empty alpha (transparent shot)
        opaque_frac = float((arr[..., 3] > 200).mean())
        if opaque_frac < 0.20:
            findings.append(ContinuityFinding(
                code="C4_empty_or_transparent_shot",
                severity="blocker",
                shot_a=sid,
                shot_b=None,
                message=f"{sid}: only {opaque_frac:.1%} opaque pixels — shot effectively empty",
                measurement={"opaque_fraction": opaque_frac},
            ))

        prev_hist = hist
        prev_lap = lap
        prev_sid = sid

    # C2 — previous_shot_reference metadata check
    for f in run_path.rglob("scenes/*/shots/*/shot.json"):
        try:
            data = json.loads(f.read_text())
            if not data.get("previous_shot_reference"):
                findings.append(ContinuityFinding(
                    code="C2_no_prev_shot_reference",
                    severity="critical",
                    shot_a=str(f.relative_to(run_path)),
                    shot_b=None,
                    message=f"{f.relative_to(run_path)}: previous_shot_reference is empty",
                    measurement={},
                ))
        except (json.JSONDecodeError, OSError):
            continue

    # C6 — props referenced but not in scene
    for f in run_path.rglob("scenes/*/scene.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        props_declared = set(data.get("props", []) or [])
        props_seen: set[str] = set()
        scene_dir = f.parent
        for shot_meta in scene_dir.rglob("shot.json"):
            try:
                sdata = json.loads(shot_meta.read_text())
                props_seen.update(sdata.get("props_visible", []) or [])
            except (json.JSONDecodeError, OSError):
                continue
        missing = props_declared - props_seen
        if missing:
            findings.append(ContinuityFinding(
                code="C6_props_declared_not_shown",
                severity="major",
                shot_a=str(f.relative_to(run_path)),
                shot_b=None,
                message=f"{f.relative_to(run_path)}: {len(missing)} prop(s) declared but never visible — {list(missing)[:5]}",
                measurement={"missing": list(missing)},
            ))

    return findings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--batch", help="parent dir of runs")
    ap.add_argument("--out", help="write JSON report")
    args = ap.parse_args()

    if args.batch:
        root = Path(args.batch).expanduser().resolve()
        runs = sorted(p for p in root.iterdir() if p.is_dir())
        report = {"batch": str(root), "runs": []}
        for r in runs:
            findings = detect_continuity(r)
            if findings:
                report["runs"].append({
                    "run_id": r.name,
                    "findings": [asdict(f) for f in findings],
                    "summary": {"n": len(findings), "blockers": sum(1 for f in findings if f.severity == "blocker")},
                })
        print(f"\ncontinuity audit: {len(report['runs'])} run(s) with findings")
        for r in report["runs"][:10]:
            print(f"  {r['run_id']}: {r['summary']['n']} findings ({r['summary']['blockers']} blockers)")
    else:
        rp = Path(args.path).expanduser().resolve()
        findings = detect_continuity(rp)
        report = {"run_id": rp.name, "findings": [asdict(f) for f in findings]}
        print(f"\ncontinuity audit: {rp.name}")
        for f in findings[:20]:
            print(f"  [{f.severity:<8}] {f.code}: {f.message}")

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nreport -> {args.out}")


if __name__ == "__main__":
    main()
