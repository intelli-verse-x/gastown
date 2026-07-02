"""G6 — Rights Auditor.

Consumes the rights_manifest.json + the G6 gate output and produces a scored
rubric suitable for council integration.

Dimensions:
    manifest_completeness  — % of assets with full schema fields
    license_compliance     — all licenses in tier's allowed list
    consent_completeness   — every voice asset has consent record
    clearance_status       — every asset cleared (no pending/blocked)
    expiry_safety          — no expired licenses
"""
from __future__ import annotations

import json
from pathlib import Path

from ._base import Auditor, AuditDimension


class RightsAuditor(Auditor):
    rubric_id = "rights"
    auditor_role = "agent://auditor/rights"
    dimensions = [
        AuditDimension("manifest_completeness", weight=2.5),
        AuditDimension("license_compliance",    weight=2.5),
        AuditDimension("consent_completeness",  weight=2.0),
        AuditDimension("clearance_status",      weight=2.0),
        AuditDimension("expiry_safety",         weight=1.0),
    ]
    pass_floor = 10.0   # Rights must be perfect or counsel waives

    def _g6(self, run_path: Path):
        g6 = run_path / "gates" / "G6.json"
        if g6.exists():
            try: return json.loads(g6.read_text())
            except json.JSONDecodeError: return None
        return None

    def score(self, run_path: Path) -> dict[str, float]:
        g6 = self._g6(run_path) or {}
        findings = g6.get("findings") or []
        codes = [f.get("code") for f in findings]
        any_missing_entry = any(c == "G6_asset_unrights_entry" for c in codes)
        any_missing_field = any(c == "G6_entry_missing_field" for c in codes)
        any_bad_license = any(c == "G6_license_disallowed" for c in codes)
        any_voice_unconsent = any(c == "G6_voice_no_consent" for c in codes)
        any_pending = any(c == "G6_clearance_pending" for c in codes)
        any_expired = any(c == "G6_license_expired" for c in codes)
        return {
            "manifest_completeness": 0.0 if (any_missing_entry or any_missing_field) else 10.0,
            "license_compliance":    0.0 if any_bad_license else 10.0,
            "consent_completeness":  0.0 if any_voice_unconsent else 10.0,
            "clearance_status":      0.0 if any_pending else 10.0,
            "expiry_safety":         0.0 if any_expired else 10.0,
        }

    def directives(self, run_path: Path, scores: dict[str, float]) -> list[str]:
        out = []
        if scores.get("manifest_completeness", 10) < 10:
            out.append("Rights: every asset must have a complete rights_manifest entry.")
        if scores.get("license_compliance", 10) < 10:
            out.append("Rights: license not in allowed list for this tier — replace asset or re-license.")
        if scores.get("consent_completeness", 10) < 10:
            out.append("Rights: voice asset missing consent record — DO NOT PUBLISH.")
        if scores.get("clearance_status", 10) < 10:
            out.append("Rights: asset clearance_status not 'cleared' — counsel review.")
        if scores.get("expiry_safety", 10) < 10:
            out.append("Rights: license expired — replace or renew before ship.")
        return out

    def verdict(self, scores, directives):
        return "APPROVED" if all(v >= 10.0 for v in scores.values()) else "BLOCK"
