"""G7 — Accessibility Auditor.

Higher-level auditor that consumes G7 gate output + caption / dub / contrast
measurements and produces a scored rubric for the council. The G7 gate itself
does the heavy ffmpeg work; this auditor synthesizes the findings into a tier-
aware verdict.

Dimensions:
    captions_coverage     — % of video duration covered by captions
    photosensitivity_safe — pass/fail from G7.A2
    wcag_contrast         — pass/fail from G7.A3
    audio_description     — present for tier aaa+
    dub_per_locale        — % of declared locales with dub
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._base import Auditor, AuditDimension


class AccessibilityAuditor(Auditor):
    rubric_id = "accessibility"
    auditor_role = "agent://auditor/accessibility"
    dimensions = [
        AuditDimension("captions_coverage",     weight=2.5),
        AuditDimension("photosensitivity_safe", weight=2.5),
        AuditDimension("wcag_contrast",         weight=1.5),
        AuditDimension("audio_description",     weight=1.5),
        AuditDimension("dub_per_locale",        weight=2.0),
    ]
    pass_floor = 7.5

    def _g7(self, run_path: Path) -> dict[str, Any] | None:
        g7 = run_path / "gates" / "G7.json"
        if g7.exists():
            try:
                return json.loads(g7.read_text())
            except json.JSONDecodeError:
                return None
        return None

    def score(self, run_path: Path) -> dict[str, float]:
        g7 = self._g7(run_path) or {}
        findings = g7.get("findings") or []
        codes = {f.get("code") for f in findings}
        captions_missing = any(c == "A1_caption_missing" for c in codes)
        photo_unsafe = any(c == "A2_photosensitivity_unsafe" for c in codes)
        contrast_bad = any(c == "A3_contrast_below_wcag" for c in codes)
        ad_missing = any(c == "A4_audio_description_missing" for c in codes)
        dub_missing = any(c == "A5_dub_missing" for c in codes)
        return {
            "captions_coverage":     0.0 if captions_missing else 10.0,
            "photosensitivity_safe": 0.0 if photo_unsafe else 10.0,
            "wcag_contrast":         3.0 if contrast_bad else 10.0,
            "audio_description":     5.0 if ad_missing else 10.0,
            "dub_per_locale":        2.0 if dub_missing else 10.0,
        }

    def directives(self, run_path: Path, scores: dict[str, float]) -> list[str]:
        out = []
        if scores.get("captions_coverage", 10) < 10:
            out.append("Accessibility: add captions (.srt / .vtt) for every output mp4.")
        if scores.get("photosensitivity_safe", 10) < 10:
            out.append("Accessibility: photosensitivity hazard — re-cut to remove >3 flashes/sec or apply PEAT-safe dim.")
        if scores.get("wcag_contrast", 10) < 10:
            out.append("Accessibility: caption contrast below WCAG AA — raise to ≥4.5:1.")
        if scores.get("audio_description", 10) < 10:
            out.append("Accessibility: add an audio_description track (required for AAA).")
        if scores.get("dub_per_locale", 10) < 10:
            out.append("Accessibility: dub missing for one or more declared locales.")
        return out
