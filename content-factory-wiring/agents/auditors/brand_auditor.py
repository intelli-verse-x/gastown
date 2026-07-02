"""G3b — Brand Auditor.

Scores a script's alignment to a brand's voice + banned terms + persona.

Inputs:
    run_path/scripts/**            — script text
    run_path/brand_persona.json    — Honcho persona (banned_terms, voice_dna, banned_topics)

Scored dimensions:
    voice_match              — how closely tone matches brand voice DNA (0-10)
    banned_term_compliance   — 10 if zero hits, deducts 5 per hit
    topic_safety             — 10 if zero hits, deducts 5 per hit
    cta_match                — does it use brand-preferred CTA phrasing
    competitor_neutrality    — no mention of named competitors

Production wiring: swap _score_voice / _score_topic with Hermes LLM calls
that take the Honcho persona as the system prompt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._base import Auditor, AuditDimension


class BrandAuditor(Auditor):
    rubric_id = "script_brand"
    auditor_role = "agent://auditor/brand"
    dimensions = [
        AuditDimension("voice_match",            weight=3.0, description="tone/cadence vs brand DNA"),
        AuditDimension("banned_term_compliance", weight=3.0, description="banned terms in script"),
        AuditDimension("topic_safety",           weight=2.0, description="banned topics"),
        AuditDimension("cta_match",              weight=1.0, description="brand CTA pattern present"),
        AuditDimension("competitor_neutrality",  weight=1.0, description="no competitor mentions"),
    ]
    pass_floor = 7.5

    def __init__(self, persona: dict[str, Any] | None = None):
        self.persona = persona

    def _load_persona(self, run_path: Path) -> dict[str, Any]:
        if self.persona is not None:
            return self.persona
        for name in ("brand_persona.json", "honcho_persona.json"):
            p = next(run_path.rglob(name), None)
            if p and p.exists():
                try:
                    return json.loads(p.read_text())
                except json.JSONDecodeError:
                    pass
        return {}

    def _gather_text(self, run_path: Path) -> str:
        parts = []
        for f in run_path.rglob("scripts/*"):
            if f.suffix in (".txt", ".md"):
                try: parts.append(f.read_text(errors="replace"))
                except OSError: pass
        return "\n".join(parts)

    def score(self, run_path: Path) -> dict[str, float]:
        persona = self._load_persona(run_path)
        text = self._gather_text(run_path)
        text_l = text.lower()

        banned_terms = [t.lower() for t in persona.get("banned_terms", [])]
        banned_topics = [t.lower() for t in persona.get("banned_topics", [])]
        competitors = [t.lower() for t in persona.get("competitors", [])]
        cta_patterns = persona.get("cta_patterns") or ["comment", "tap", "follow"]
        voice_keywords = persona.get("voice_keywords") or []

        banned_hits = sum(1 for t in banned_terms if t and t in text_l)
        topic_hits = sum(1 for t in banned_topics if t and t in text_l)
        comp_hits = sum(1 for t in competitors if t and t in text_l)
        cta_hit = any(c in text_l for c in cta_patterns)
        voice_hit = sum(1 for k in voice_keywords if k.lower() in text_l) / max(len(voice_keywords) or 1, 1)

        return {
            "voice_match":            round(min(10.0, 6.0 + 4.0 * voice_hit), 2),
            "banned_term_compliance": float(max(0, 10 - 5 * banned_hits)),
            "topic_safety":           float(max(0, 10 - 5 * topic_hits)),
            "cta_match":              10.0 if cta_hit else 5.0,
            "competitor_neutrality":  float(max(0, 10 - 10 * comp_hits)),
        }

    def directives(self, run_path: Path, scores: dict[str, float]) -> list[str]:
        out = []
        if scores.get("banned_term_compliance", 10) < 10:
            out.append("Brand: remove banned term(s); replace with persona-preferred alternative.")
        if scores.get("topic_safety", 10) < 10:
            out.append("Brand: rewrite to avoid banned topic.")
        if scores.get("competitor_neutrality", 10) < 10:
            out.append("Brand: remove competitor mention or replace with category language.")
        if scores.get("voice_match", 10) < 7:
            out.append("Brand: tone drifts from voice DNA — see persona.voice_examples for reference.")
        if scores.get("cta_match", 10) < 7:
            out.append("Brand: missing approved CTA phrasing.")
        return out
