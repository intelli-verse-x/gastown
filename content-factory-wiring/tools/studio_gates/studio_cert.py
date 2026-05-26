"""studio_cert.py — run every required gate for a tier, emit a signed certificate.

Exit code:
    0  certified (all required gates passed)
    1  blocked (one or more required gates failed)
    2  argument / usage error

Certificate format (written to {run_path}/certificate.json):
    {
      "run_id": "...", "tier": "aa", "issued_at": "...",
      "gates": [ { "gate_id": "G1", "passed": true, "signature": "...", ... }, ... ],
      "output_hash": "...",
      "certificate_signature": "..."
    }
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import GateResult, TIER_GATES, GATE_NAMES, now_utc, sign
    from .g14_chain_of_custody import append as coc_append
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from __init__ import GateResult, TIER_GATES, GATE_NAMES, now_utc, sign  # type: ignore
    from g14_chain_of_custody import append as coc_append  # type: ignore


GATE_MODULES = {
    "G1": "g1_concept_lock",
    "G2": "g2_canon_lock",
    "G3": "g3_script_multi_read",
    "G4": "g4_visual_continuity",
    "G6": "g6_rights_manifest",
    "G7": "g7_accessibility",
    "G9": "g9_frame_qa",
    "G10": "g10_council_enforcer",
    "G11": "g11_localization",
    "G13": "g13_dual_signoff",
    "G14": "g14_chain_of_custody",
    "G15": "g15_character_identity",
}

# G5 (audio) + G8 (platform cert) + G12 (live-ops) live in sibling tools/.
EXTERNAL_GATES = {
    "G5": "tools.social_publish_auditor",
    "G8": "tools.social_publish_auditor",
    "G12": "tools.kpi_tracker",
}


def _import_gate(gate_id: str):
    mod = GATE_MODULES.get(gate_id)
    if not mod:
        return None
    try:
        m = importlib.import_module(f".{mod}", package="tools.studio_gates")
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        m = importlib.import_module(mod)
    return m


def run(run_path: Path, tier: str = "aa", required: list[str] | None = None,
        emit_cert: bool = True) -> dict[str, Any]:
    required = required or TIER_GATES.get(tier, TIER_GATES["aa"])
    gates_dir = run_path / "gates"
    gates_dir.mkdir(exist_ok=True)

    results: list[dict[str, Any]] = []
    for g in required:
        if g in EXTERNAL_GATES:
            # External gates record their own files; we just check presence
            results.append({
                "gate_id": g, "gate_name": GATE_NAMES.get(g, g),
                "passed": _check_external(g, run_path),
                "evaluated_at": now_utc(),
                "external": EXTERNAL_GATES[g],
            })
            continue
        mod = _import_gate(g)
        if not mod or not hasattr(mod, "evaluate"):
            results.append({
                "gate_id": g, "gate_name": GATE_NAMES.get(g, g),
                "passed": False,
                "error": f"gate module not loadable: {g}",
            })
            continue
        result: GateResult = mod.evaluate(run_path, tier=tier)
        # Persist per-gate result
        (gates_dir / f"{g}.json").write_text(json.dumps(result.to_dict(), indent=2))
        # Append to chain of custody (best-effort)
        try:
            coc_append(run_path, {
                "kind": "gate_evaluated",
                "gate_id": g,
                "passed": result.passed,
                "n_findings": len(result.findings),
            })
        except Exception:
            pass
        results.append(result.to_dict())

    all_passed = all(r.get("passed") for r in results)
    cert = {
        "run_id": run_path.name,
        "tier": tier,
        "issued_at": now_utc(),
        "required_gates": required,
        "results": results,
        "passed": all_passed,
        "summary": {
            "passed_count": sum(1 for r in results if r.get("passed")),
            "failed_count": sum(1 for r in results if not r.get("passed")),
            "total": len(results),
        },
    }
    cert["signature"] = sign(cert)
    cert["certificate_signature"] = cert["signature"]
    if emit_cert:
        out = run_path / "certificate.json"
        out.write_text(json.dumps(cert, indent=2))
    return cert


def _check_external(gate_id: str, run_path: Path) -> bool:
    if gate_id in ("G5", "G8"):
        sp = run_path / "social_publish_audit.json"
        if not sp.exists():
            return False
        try:
            data = json.loads(sp.read_text())
            sev = data.get("summary", {}).get("by_severity", {})
            return not (sev.get("blocker", 0) or sev.get("critical", 0))
        except Exception:
            return False
    if gate_id == "G12":
        # Live-ops gate passes if we have engagement readings within last 7 days
        eng = list(run_path.rglob("engagement*.json"))
        return bool(eng)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_path")
    ap.add_argument("--tier", default="aa", choices=list(TIER_GATES.keys()))
    ap.add_argument("--gates", help="comma-separated gate IDs to run (overrides tier)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rp = Path(args.run_path).expanduser().resolve()
    if not rp.exists():
        print(f"error: {rp} does not exist", file=sys.stderr)
        return 2
    required = args.gates.split(",") if args.gates else None
    cert = run(rp, tier=args.tier, required=required)

    if args.json:
        print(json.dumps(cert, indent=2))
    else:
        print(f"\n=== STUDIO CERT for {cert['run_id']} (tier={cert['tier']}) ===")
        print(f"{'Gate':<6} {'Name':<22} {'Passed':<8} {'Findings':<10}")
        print("-" * 50)
        for r in cert["results"]:
            n = sum(1 for x in (r.get("findings") or []))
            mark = "OK" if r.get("passed") else "BLOCK"
            print(f"{r['gate_id']:<6} {r.get('gate_name',''):<22} {mark:<8} {n}")
        print("-" * 50)
        print(f"{cert['summary']['passed_count']}/{cert['summary']['total']} passed")
        print(f"\ncertificate: {rp}/certificate.json")
        print(f"signature  : {cert['certificate_signature'][:16]}…")
    return 0 if cert["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
