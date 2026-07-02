"""Auditor agents for content-factory studio-grade gates.

Each auditor produces council_audits/<rubric_id>_audit.json with an HMAC signature.
The gate enforcers (G3, G6, G7, G10) consume these and block on FAIL/BLOCK.

Usage:
    from agents.auditors import BrandAuditor, LegalAuditor, CulturalAuditor, \
                                AccessibilityAuditor, RightsAuditor

    for A in (BrandAuditor, LegalAuditor):
        A().run(run_path)

    for locale in run_meta.locales:
        CulturalAuditor(locale).run(run_path)
"""
from .brand_auditor import BrandAuditor
from .legal_auditor import LegalAuditor
from .cultural_auditor import CulturalAuditor
from .accessibility_auditor import AccessibilityAuditor
from .rights_auditor import RightsAuditor

__all__ = [
    "BrandAuditor", "LegalAuditor", "CulturalAuditor",
    "AccessibilityAuditor", "RightsAuditor",
]
