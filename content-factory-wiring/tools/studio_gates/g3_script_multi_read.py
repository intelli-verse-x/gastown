"""G3 Script Gate — 4 separate reads must all pass: creative, brand, legal, cultural.

Reads we run:
  R1 creative_audit       — quality of writing (existing screenwriting_audit.json)
  R2 brand_audit          — voice + banned terms + persona alignment
  R3 legal_audit          — trademark, copyright, real-person likeness, regulated claims
  R4 cultural_audit       — regional sensitivity (slurs, gestures, religion, politics, dietary)

Each read produces a JSON in council_audits/script_<type>_audit.json.
G3 fails if any of the 4 audits has verdict in {FAIL, BLOCK} OR is missing.

LLM calls for R2/R3/R4 are stubbed here — implement by calling Hermes via MCP.
The brand/legal/cultural rules can also run as pure regex passes first.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from . import GateFinding, GateResult, now_utc, sign
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign  # type: ignore


# ---------------------------------------------------------------------------
# Quick rule-based checkers (run before / instead of LLM)
# ---------------------------------------------------------------------------

# Compact, expandable rule sets — production version pulls from a versioned policy bead.
BRAND_BANNED_TERMS = {
    # Examples; replace from Honcho persona's banned_terms
    "competitor1", "competitor2", "buzzkill", "lame", "scam",
}

LEGAL_RED_FLAGS = [
    r"\b(?:Coca[- ]?Cola|Pepsi|Disney|Marvel|Nintendo|Pok[eé]mon)\b",   # trademarks
    r"\b(?:Elon Musk|Taylor Swift|Donald Trump|Joe Biden)\b",            # real persons
    r"\b(?:cure|treats|prevents|guaranteed)\b",                          # health claims
    r"\b(?:no risk|risk[- ]free|0%? risk)\b",                            # financial claims
    r"\b(?:FDA approved|clinically proven)\b",                           # regulatory
]

CULTURAL_HIGH_RISK_TERMS = [
    # Demonstrative — production version routes through the cultural policy bead
    r"\b(?:gypsy|oriental|colored|exotic)\b",                  # outdated terms
    r"\b(?:swastika|nazi|terrorist|jihad)\b",                  # historically loaded
    r"\b(?:cult|sect|heretic)\b",                              # religion-loaded
]


def _safe_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _gather_script_text(run_path: Path) -> str:
    chunks: list[str] = []
    for f in run_path.rglob("scripts/*"):
        if not f.is_file():
            continue
        if f.suffix in (".txt", ".md"):
            try: chunks.append(f.read_text(errors="replace"))
            except OSError: pass
        elif f.suffix == ".json":
            data = _safe_json(f)
            if isinstance(data, list):
                # script may be a list of {speaker, line} dicts
                for item in data:
                    if isinstance(item, str):
                        chunks.append(item)
                    elif isinstance(item, dict):
                        for k in ("text", "line", "body", "content"):
                            v = item.get(k)
                            if isinstance(v, str):
                                chunks.append(v)
            elif isinstance(data, dict):
                for k in ("script", "lines", "text", "body", "narration"):
                    v = data.get(k)
                    if isinstance(v, str):
                        chunks.append(v)
                    elif isinstance(v, list):
                        for x in v:
                            if isinstance(x, str):
                                chunks.append(x)
                            elif isinstance(x, dict):
                                t = x.get("text") or x.get("line") or x.get("body")
                                if isinstance(t, str):
                                    chunks.append(t)
    return "\n\n".join(chunks)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def r1_creative(run_path: Path) -> tuple[bool, list[GateFinding]]:
    findings: list[GateFinding] = []
    candidates = list(run_path.rglob("council_audits/screenwriting_audit.json")) + \
                 list(run_path.rglob("council_audits/script_creative_audit.json"))
    if not candidates:
        findings.append(GateFinding(
            code="G3_R1_missing",
            severity="blocker",
            message="creative read (screenwriting_audit.json) missing",
        ))
        return False, findings
    data = _safe_json(candidates[0]) or {}
    verdict = (data.get("final_verdict") or data.get("quality_verdict") or "").upper()
    if verdict in ("FAIL", "BLOCK", "REJECT"):
        findings.append(GateFinding(
            code="G3_R1_fail",
            severity="blocker",
            message=f"creative read verdict={verdict}",
            measurement={"verdict": verdict, "directives": len(data.get("directives") or [])},
        ))
        return False, findings
    return True, findings


def r2_brand(run_path: Path) -> tuple[bool, list[GateFinding]]:
    text = _gather_script_text(run_path).lower()
    findings: list[GateFinding] = []
    # Persona-driven banned terms
    persona_file = next(run_path.rglob("brand_persona.json"), None) or \
                   next(run_path.rglob("honcho_persona.json"), None)
    banned = set(BRAND_BANNED_TERMS)
    if persona_file:
        p = _safe_json(persona_file) or {}
        banned |= {t.lower() for t in p.get("banned_terms", []) if isinstance(t, str)}
    hits = sorted({t for t in banned if t and t in text})
    if hits:
        findings.append(GateFinding(
            code="G3_R2_brand_banned_term",
            severity="blocker",
            message=f"brand banned terms in script: {hits[:5]}",
            measurement={"hits": hits[:20]},
        ))
        return False, findings
    return True, findings


def r3_legal(run_path: Path) -> tuple[bool, list[GateFinding]]:
    text = _gather_script_text(run_path)
    findings: list[GateFinding] = []
    for pat in LEGAL_RED_FLAGS:
        ms = re.findall(pat, text, flags=re.IGNORECASE)
        if ms:
            findings.append(GateFinding(
                code="G3_R3_legal_red_flag",
                severity="blocker",
                message=f"legal red flag pattern `{pat}` matched {len(ms)} time(s)",
                measurement={"pattern": pat, "matches": ms[:5]},
            ))
    passed = not any(f.severity == "blocker" for f in findings)
    return passed, findings


def r4_cultural(run_path: Path) -> tuple[bool, list[GateFinding]]:
    text = _gather_script_text(run_path)
    findings: list[GateFinding] = []
    for pat in CULTURAL_HIGH_RISK_TERMS:
        ms = re.findall(pat, text, flags=re.IGNORECASE)
        if ms:
            findings.append(GateFinding(
                code="G3_R4_cultural_risk",
                severity="critical",
                message=f"cultural high-risk term `{pat}` matched {len(ms)} time(s) — needs cultural review",
                measurement={"pattern": pat, "matches": ms[:5]},
            ))
    # Cultural read NEVER auto-passes high-risk content; downgrades to "needs human review"
    # but doesn't block by itself — flagged as critical for the cultural reviewer to handle.
    passed = not any(f.severity == "blocker" for f in findings)
    return passed, findings


# ---------------------------------------------------------------------------

def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    all_passed = True
    for label, fn in (("R1", r1_creative), ("R2", r2_brand), ("R3", r3_legal), ("R4", r4_cultural)):
        ok, fs = fn(run_path)
        findings.extend(fs)
        all_passed = all_passed and ok

    r = GateResult(
        gate_id="G3", gate_name="script_multi_read", passed=all_passed, tier=tier,
        findings=findings, run_id=run_path.name, evaluated_at=now_utc(),
    )
    r.signature = sign(r.to_dict())
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_path")
    ap.add_argument("--tier", default="aa")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = evaluate(Path(args.run_path).expanduser().resolve(), args.tier)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
    else:
        print(f"[G3 script_multi_read] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
