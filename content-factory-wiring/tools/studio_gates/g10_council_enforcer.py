"""G10 Council Enforcer — block ship when council directives are unapplied.

For every council_audits/*_audit.json:
  • verdict in {APPROVED, PASS} → ok
  • verdict in {FAIL, BLOCK} → BLOCKER
  • verdict in {PASS_WITH_NOTES, NEEDS_REVIEW}:
      - require redo_count >= min(n_directives, max_redos) OR
      - require approved_output is not null OR
      - require an explicit waive bead reference in audit.waiver_bead
  • Reject any audit with auto_pass_reason="time_budget" (NS-3a)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from . import GateFinding, GateResult, now_utc, sign
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign  # type: ignore


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    audit_files = list(run_path.rglob("council_audits/*_audit.json"))
    if not audit_files:
        return _result(
            [GateFinding(code="G10_no_audit", severity="critical",
                         message="No council audits found — required for tier ≥ aa")],
            run_path, tier, passed=tier in ("internal", "indie"),
        )

    for f in audit_files:
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rel = str(f.relative_to(run_path))
        verdict = (d.get("final_verdict") or d.get("quality_verdict") or "").upper()
        n_directives = len(d.get("directives") or [])
        redo = int(d.get("redo_count") or 0)
        max_redos = int(d.get("max_redos") or 0)
        approved = d.get("approved_output")
        waiver = d.get("waiver_bead")

        # Hard block on auto-pass time budget
        auto_reason = d.get("auto_pass_reason") or d.get("auto_passed_reason")
        if auto_reason == "time_budget":
            findings.append(GateFinding(
                code="G10_time_budget_autopass",
                severity="blocker",
                message=f"{rel}: auto-passed due to time_budget — NS-3a hardstop",
                measurement={"audit_file": rel},
            ))
            continue

        if verdict in ("FAIL", "BLOCK", "REJECT"):
            findings.append(GateFinding(
                code="G10_fail_verdict",
                severity="blocker",
                message=f"{rel}: verdict=FAIL with {n_directives} directives",
                measurement={"verdict": verdict, "directives": n_directives},
            ))
            continue

        if verdict in ("PASS_WITH_NOTES", "NEEDS_REVIEW") and n_directives > 0:
            required = min(n_directives, max(max_redos, 1))
            satisfied = redo >= required or approved is not None or waiver
            if not satisfied:
                findings.append(GateFinding(
                    code="G10_directives_unapplied",
                    severity="blocker",
                    message=(
                        f"{rel}: verdict={verdict}, {n_directives} directives, "
                        f"redo_count={redo}/{required} required, no waiver bead"
                    ),
                    measurement={
                        "audit_file": rel,
                        "verdict": verdict,
                        "redo_count": redo,
                        "required_redos": required,
                    },
                ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G10", gate_name="council_enforcer", passed=passed, tier=tier,
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
        print(f"[G10 council_enforcer] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
