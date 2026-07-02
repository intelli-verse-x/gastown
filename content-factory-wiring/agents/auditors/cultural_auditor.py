"""G3d — Cultural Auditor (per-locale).

Scores cultural-fit for a target locale. Stubs use a small global pattern bank;
production version routes through a per-locale reviewer agent and pulls the
pattern bank from `cultural_policy_bead://<locale>`.

Dimensions:
    sensitive_language    — outdated / racialized / colonialist terms
    religious_safety      — religious imagery used appropriately
    political_neutrality  — no partisan signaling unless explicitly approved
    gesture_safety        — hand gestures with adverse meaning in locale absent (visual check
                            stubbed; production uses pose estimator on storyboard frames)
    holiday_calendar      — date claims align with locale's calendar (if applicable)
"""
from __future__ import annotations

import re
from pathlib import Path

from ._base import Auditor, AuditDimension


GLOBAL_HIGH_RISK = [
    r"\b(?:gypsy|oriental|colored|exotic|primitive|savage)\b",
    r"\b(?:swastika|nazi|terrorist|jihad)\b",
    r"\b(?:cult|sect|heretic)\b",
]

LOCALE_OVERLAYS: dict[str, list[str]] = {
    "es-MX": [r"\bm[ée]xicano\s+illegal\b"],
    "ja-JP": [r"\b(?:weeb|kamikaze\s+(?:for|to))\b"],
    "ar":    [r"\b(?:harem|infidel)\b"],
}


class CulturalAuditor(Auditor):
    rubric_id_base = "script_cultural"
    auditor_role = "agent://auditor/cultural"
    dimensions = [
        AuditDimension("sensitive_language",   weight=3.0),
        AuditDimension("religious_safety",     weight=2.0),
        AuditDimension("political_neutrality", weight=2.0),
        AuditDimension("gesture_safety",       weight=1.5),
        AuditDimension("holiday_calendar",     weight=1.5),
    ]
    pass_floor = 8.5

    def __init__(self, locale: str = "global"):
        self.locale = locale
        self.rubric_id = f"{self.rubric_id_base}_{locale.replace('-', '_')}"

    def _gather_text(self, run_path: Path) -> str:
        parts = []
        for f in run_path.rglob("scripts/*"):
            if f.suffix in (".txt", ".md"):
                try: parts.append(f.read_text(errors="replace"))
                except OSError: pass
        return "\n".join(parts)

    def score(self, run_path: Path) -> dict[str, float]:
        text = self._gather_text(run_path)
        patterns = GLOBAL_HIGH_RISK + LOCALE_OVERLAYS.get(self.locale, [])
        hits = 0
        for pat in patterns:
            hits += len(re.findall(pat, text, flags=re.IGNORECASE))
        # All dimensions share the rule-based score for the stub; production uses an LLM per dim.
        s = 10.0 if hits == 0 else max(0.0, 10.0 - 3.0 * hits)
        return {d.name: s for d in self.dimensions}

    def directives(self, run_path: Path, scores: dict[str, float]) -> list[str]:
        if all(v >= self.pass_floor for v in scores.values()):
            return []
        return [
            f"Cultural[{self.locale}]: requires per-locale reviewer sign-off. "
            f"Spawn bd create --type=cultural_review --locale={self.locale}."
        ]

    def verdict(self, scores, directives):
        # Any high-risk pattern routes to human reviewer
        if directives:
            return "NEEDS_REVIEW"
        return "APPROVED"
