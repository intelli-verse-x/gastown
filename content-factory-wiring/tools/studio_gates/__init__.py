"""Studio-grade enforcement gates G1-G14.

Each gate exposes:
    evaluate(run_path: Path, tier: str = "aa") -> GateResult

GateResult is signed (HMAC-SHA256) and gets appended to chain_of_custody.jsonl.

Run via:
    python -m tools.studio_gates.studio_cert <run_path> --tier=aa

CLI exit code 0 = certified, !=0 = blocked. Refinery is bound to this exit code.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------

@dataclass
class GateFinding:
    code: str
    severity: str          # blocker | critical | high | medium | low
    message: str
    measurement: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    gate_id: str            # G1..G14
    gate_name: str
    passed: bool
    tier: str
    findings: list[GateFinding] = field(default_factory=list)
    run_id: str = ""
    evaluated_at: str = ""
    signature: str = ""     # HMAC-SHA256 over canonical JSON

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_name": self.gate_name,
            "passed": self.passed,
            "tier": self.tier,
            "findings": [asdict(f) for f in self.findings],
            "run_id": self.run_id,
            "evaluated_at": self.evaluated_at,
            "signature": self.signature,
        }


# ---------------------------------------------------------------------------
# Signing — HMAC-SHA256 over canonical JSON
# ---------------------------------------------------------------------------

def _signing_key() -> bytes:
    key = os.environ.get("CONTENTX_CERT_KEY", "").encode()
    if not key:
        # Dev-mode key; production must set CONTENTX_CERT_KEY from vault
        key = b"dev-mode-not-for-production-use-CONTENTX_CERT_KEY"
    return key


def sign(payload: dict[str, Any]) -> str:
    # Canonical: keys sorted, no trailing whitespace, exclude existing signature
    safe = {k: v for k, v in payload.items() if k != "signature"}
    canonical = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_signing_key(), canonical, hashlib.sha256).hexdigest()


def verify(payload: dict[str, Any]) -> bool:
    expected = sign(payload)
    return hmac.compare_digest(expected, payload.get("signature", ""))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Gate registry
# ---------------------------------------------------------------------------

GATE_NAMES = {
    "G1": "concept_lock",
    "G2": "canon_lock",
    "G3": "script_multi_read",
    "G4": "visual_continuity",
    "G5": "audio_mix",                   # handled by social_publish_auditor.py
    "G6": "rights_manifest",
    "G7": "accessibility",
    "G8": "platform_cert",               # handled by social_publish_auditor.py
    "G9": "frame_qa",
    "G10": "council_enforcer",
    "G11": "localization",
    "G12": "live_ops_feedback",          # handled by postiz_engagement_scraper.py
    "G13": "dual_signoff",
    "G14": "chain_of_custody",
    "G15": "character_identity",
}

TIER_GATES = {
    "internal":  ["G1", "G14"],
    "indie":     ["G1", "G3", "G5", "G6", "G10", "G14", "G15"],
    "aa":        ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G13", "G14", "G15"],
    "aaa":       ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G13", "G14", "G15"],
    "live-aaa":  list(GATE_NAMES.keys()),
}


__all__ = [
    "GateFinding", "GateResult",
    "sign", "verify", "now_utc",
    "GATE_NAMES", "TIER_GATES",
]
