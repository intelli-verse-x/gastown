"""Base class for content-factory auditor agents (G3a–d, G6, G7).

Each subclass implements:
    rubric_id          — short token used in council_audits/<rubric_id>_audit.json
    dimensions         — list of (name, weight, description) for each scored axis
    score(run_path)    — returns Dict[dim, float] in [0, 10]
    directives(run_path, scores) — returns list[str] of remediation directives
    verdict(scores, directives) — returns one of APPROVED|PASS_WITH_NOTES|NEEDS_REVIEW|FAIL

Produces:
    council_audits/<rubric_id>_audit.json  — feeds G3 / G6 / G7 / G10
    gate_signature                          — HMAC over canonical audit body

Auditors are stateless and idempotent; the same run_path always yields the same
score (given the same input policy bead). Run them in parallel inside a Hermes
subagent fan-out.

The bodies below are skeletons — drop in Hermes LLM calls or your existing
council scorer; the scaffolding (sign, persist, escalate to bd) is here.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reach up to the studio_gates HMAC helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "studio_gates"))
from __init__ import sign, now_utc  # type: ignore  # noqa: E402


# ---------------------------------------------------------------------------
# Hermes MCP LLM hook
# ---------------------------------------------------------------------------
#
# If HERMES_MCP_URL is set (e.g. http://localhost:8800/mcp), the auditor will
# call the `score_rubric` tool on that MCP server with the rubric definition
# and the gathered evidence. The MCP server is expected to invoke a model and
# return per-dimension scores in JSON.
#
# Fallback: if the MCP call fails for any reason, the auditor uses its
# subclass-defined deterministic `score()` body.
# ---------------------------------------------------------------------------

def _hermes_mcp_available() -> bool:
    return bool(os.environ.get("HERMES_MCP_URL"))


def hermes_score(
    rubric_id: str,
    dimensions: list[dict[str, Any]],
    evidence: dict[str, Any],
    *,
    timeout_s: float = 30.0,
) -> dict[str, float] | None:
    """Call Hermes MCP `score_rubric` tool. Returns scores dict on success, else None.

    Schema sent:
        {
          "tool": "score_rubric",
          "args": {
            "rubric_id": ...,
            "dimensions": [{name, weight, description}, ...],
            "evidence": {script, brand_book_ref, ...}
          }
        }
    Expected response:
        {"scores": {dim_name: float in [0,10], ...}}
    """
    url = os.environ.get("HERMES_MCP_URL")
    if not url:
        return None
    try:
        import httpx  # type: ignore
    except ImportError:
        return None
    payload = {
        "tool": "score_rubric",
        "args": {
            "rubric_id": rubric_id,
            "dimensions": dimensions,
            "evidence": evidence,
        },
    }
    try:
        with httpx.Client(timeout=timeout_s) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        scores = data.get("scores") or {}
        return {k: float(v) for k, v in scores.items() if isinstance(v, (int, float))}
    except Exception:
        return None


@dataclass
class AuditDimension:
    name: str
    weight: float
    description: str = ""


@dataclass
class AuditResult:
    rubric_id: str
    auditor: str
    auditor_role: str
    run_id: str
    evaluated_at: str
    scores: dict[str, float]
    overall_score: float
    final_verdict: str          # APPROVED | PASS_WITH_NOTES | NEEDS_REVIEW | FAIL | BLOCK
    directives: list[str]
    redo_count: int = 0
    max_redos: int = 1
    approved_output: str | None = None
    waiver_bead: str | None = None
    scoring_source: str = "deterministic_rule"  # or "hermes_mcp"
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "rubric_id": self.rubric_id,
            "auditor": self.auditor,
            "auditor_role": self.auditor_role,
            "run_id": self.run_id,
            "evaluated_at": self.evaluated_at,
            "scores": self.scores,
            "overall_score": self.overall_score,
            "final_verdict": self.final_verdict,
            "directives": self.directives,
            "redo_count": self.redo_count,
            "max_redos": self.max_redos,
            "approved_output": self.approved_output,
            "waiver_bead": self.waiver_bead,
            "scoring_source": self.scoring_source,
        }
        d["signature"] = self.signature
        return d


class Auditor:
    rubric_id: str = "auditor_base"
    auditor_role: str = "agent://auditor/base"
    dimensions: list[AuditDimension] = []
    pass_floor: float = 7.0
    notes_floor: float = 5.5

    # ------------------------------------------------------------------
    # Subclasses override these three
    # ------------------------------------------------------------------
    def score(self, run_path: Path) -> dict[str, float]:
        raise NotImplementedError

    def gather_evidence(self, run_path: Path) -> dict[str, Any]:
        """Subclasses can override to send richer evidence to Hermes MCP.

        Default: aggregate the script + key metadata files.
        """
        ev: dict[str, Any] = {"run_id": run_path.name}
        for sub in ("script.json", "metadata/pitch_deck.json", "studio_bible.json"):
            f = run_path / sub
            if f.exists():
                try:
                    ev[sub] = json.loads(f.read_text(errors="replace"))[:5000] \
                        if isinstance(json.loads(f.read_text(errors="replace")), str) \
                        else json.loads(f.read_text(errors="replace"))
                except Exception:
                    pass
        return ev

    def llm_score(self, run_path: Path) -> dict[str, float] | None:
        """Call Hermes MCP. Returns None if unavailable; caller falls back to score()."""
        if not _hermes_mcp_available():
            return None
        dims = [{"name": d.name, "weight": d.weight, "description": d.description}
                for d in self.dimensions]
        try:
            evidence = self.gather_evidence(run_path)
        except Exception:
            evidence = {"run_id": run_path.name, "evidence_error": True}
        return hermes_score(self.rubric_id, dims, evidence)

    def directives(self, run_path: Path, scores: dict[str, float]) -> list[str]:
        return []

    def verdict(self, scores: dict[str, float], directives: list[str]) -> str:
        if not scores:
            return "NEEDS_REVIEW"
        overall = self._weighted(scores)
        if overall >= self.pass_floor and not directives:
            return "APPROVED"
        if overall >= self.notes_floor:
            return "PASS_WITH_NOTES"
        if overall >= 3.0:
            return "NEEDS_REVIEW"
        return "FAIL"

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------
    def run(self, run_path: Path, redo_count: int = 0, max_redos: int = 1) -> AuditResult:
        # Prefer Hermes MCP LLM scoring when available; gracefully fall back.
        llm_scores = self.llm_score(run_path)
        scoring_source = "hermes_mcp"
        if llm_scores and all(d.name in llm_scores for d in self.dimensions):
            scores = llm_scores
        else:
            scores = self.score(run_path)
            scoring_source = "deterministic_rule"
        directives = self.directives(run_path, scores)
        verdict = self.verdict(scores, directives)
        result = AuditResult(
            rubric_id=self.rubric_id,
            auditor=self.__class__.__name__,
            auditor_role=self.auditor_role,
            run_id=run_path.name,
            evaluated_at=now_utc(),
            scores=scores,
            overall_score=round(self._weighted(scores), 2),
            final_verdict=verdict,
            directives=directives,
            redo_count=redo_count,
            max_redos=max_redos,
            scoring_source=scoring_source,
        )
        body = result.to_dict()
        body.pop("signature", None)
        result.signature = sign(body)

        audit_dir = run_path / "council_audits"
        audit_dir.mkdir(exist_ok=True)
        (audit_dir / f"{self.rubric_id}_audit.json").write_text(json.dumps(result.to_dict(), indent=2))
        return result

    def _weighted(self, scores: dict[str, float]) -> float:
        if not self.dimensions:
            return sum(scores.values()) / max(len(scores), 1)
        total_w = sum(d.weight for d in self.dimensions) or 1.0
        return sum(scores.get(d.name, 0) * d.weight for d in self.dimensions) / total_w
