"""G3c — Legal Auditor.

Pattern-based pre-filter. ANY hit is escalated to human counsel; this auditor
never auto-approves a hit. Counsel can attach a waiver_bead reference.

Dimensions:
    trademark_clearance       — no unlicensed trademarks
    real_person_likeness      — no named real persons without consent
    regulated_claims          — no medical/financial/safety claims
    defamation_safety         — no actionable statements about identifiable parties
    music_rights              — no unlicensed music references

Production wiring: pattern bank lives in a `legal_policy_bead` and is updated
by counsel; this stub embeds a small example bank.
"""
from __future__ import annotations

import re
from pathlib import Path

from ._base import Auditor, AuditDimension


PATTERN_BANKS: dict[str, list[str]] = {
    "trademark_clearance": [
        r"\b(?:Coca[- ]?Cola|Pepsi|Disney|Marvel|Nintendo|Pok[eé]mon|Roblox|Fortnite|TikTok|YouTube|Instagram|Twitter|X Corp)\b",
    ],
    "real_person_likeness": [
        r"\b(?:Elon Musk|Taylor Swift|Donald Trump|Joe Biden|Mark Zuckerberg|Jeff Bezos)\b",
    ],
    "regulated_claims": [
        r"\b(?:cures?|treats?|prevents?|guaranteed (?:to )?(?:cure|fix))\b",
        r"\b(?:FDA approved|clinically proven|doctor[- ]recommended)\b",
        r"\b(?:no risk|risk[- ]free|0%? risk|guaranteed returns?)\b",
        r"\b(?:government secret|the truth they don't want you to know)\b",
    ],
    "defamation_safety": [
        r"\b(?:fraud|scammer|criminal|liar)\b\s+\b[A-Z][a-z]+\s+[A-Z][a-z]+\b",  # accusation + ProperName
    ],
    "music_rights": [
        r"#(?:taylor swift|the weeknd|drake|billie eilish|olivia rodrigo)\b",
    ],
}


class LegalAuditor(Auditor):
    rubric_id = "script_legal"
    auditor_role = "agent://auditor/legal"
    dimensions = [
        AuditDimension(k, weight=2.0) for k in PATTERN_BANKS.keys()
    ]
    # Legal NEVER auto-approves below 10 in any dimension — counsel must waive.
    pass_floor = 10.0

    def _gather_text(self, run_path: Path) -> str:
        parts = []
        for f in run_path.rglob("scripts/*"):
            if f.suffix in (".txt", ".md"):
                try: parts.append(f.read_text(errors="replace"))
                except OSError: pass
        return "\n".join(parts)

    def score(self, run_path: Path) -> dict[str, float]:
        text = self._gather_text(run_path)
        scores: dict[str, float] = {}
        for dim, patterns in PATTERN_BANKS.items():
            hits = 0
            for pat in patterns:
                hits += len(re.findall(pat, text, flags=re.IGNORECASE))
            # Legal: any hit → 0 in that dimension (human review required)
            scores[dim] = 10.0 if hits == 0 else 0.0
        return scores

    def directives(self, run_path: Path, scores: dict[str, float]) -> list[str]:
        out = []
        text = self._gather_text(run_path)
        for dim, patterns in PATTERN_BANKS.items():
            for pat in patterns:
                m = re.findall(pat, text, flags=re.IGNORECASE)
                if m:
                    out.append(
                        f"Legal[{dim}]: matched `{pat}` ({len(m)} hit(s)). "
                        f"Requires counsel review. Bead: bd create --type=legal_review."
                    )
        return out

    def verdict(self, scores, directives):
        # Legal verdict is binary: APPROVED only if every dim is perfect.
        if all(v >= 10.0 for v in scores.values()) and not directives:
            return "APPROVED"
        return "BLOCK"
