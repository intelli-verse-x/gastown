"""
run_id_auditor.py — detect the 6 per-run failure modes (F1–F6) on any content-factory run folder.

Usage:
    python run_id_auditor.py <run_folder> [--json] [--out <report.json>]
    python run_id_auditor.py --batch <parent_dir> [--out <batch_report.json>]

Failure modes detected:
    F1  silent abort        — checkpoint status=aborted/failed without surfaced alert
    F2  gate-fail-but-ship  — quality/*.passed=false yet publish artifacts present
    F3  council unapplied   — council audit final_verdict ∈ {FAIL,PASS_WITH_NOTES} with applied_directives=0
    F4  blocker gap silenced — gap_reports[].severity=blocker but pipeline progressed past
    F5  open run_feedback   — run_feedback.json status=needs_review with empty engagement_metrics
    F6  nested duplication  — same-named state files copied under production/production/scenes/*/

Output: structured JSON gap report, ready to feed into run_id_repairer.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    code: str
    severity: str  # blocker | critical | high | medium | low
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_action: str = ""


@dataclass
class RunAudit:
    run_id: str
    run_path: str
    pipeline_kind: str | None
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "run_id": self.run_id,
            "run_path": self.run_path,
            "pipeline_kind": self.pipeline_kind,
            "findings": [asdict(f) for f in self.findings],
            "stats": self.stats,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total": len(self.findings),
                "by_severity": _count_by(self.findings, "severity"),
                "by_code": _count_by(self.findings, "code"),
            },
        }
        return d


def _count_by(items: list[Finding], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in items:
        v = getattr(f, key)
        out[v] = out.get(v, 0) + 1
    return out


# ---------------------------------------------------------------------------
# JSON utilities
# ---------------------------------------------------------------------------

def _load_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _find_files(root: Path, name: str) -> list[Path]:
    return [p for p in root.rglob(name) if p.is_file()]


# ---------------------------------------------------------------------------
# Per-failure-mode detectors
# ---------------------------------------------------------------------------

def detect_f1_silent_abort(root: Path) -> list[Finding]:
    """F1 — checkpoint says aborted/failed but no surfacing artifact."""
    out: list[Finding] = []
    ckpt_path = root / "checkpoint.json"
    ckpt = _load_json(ckpt_path) if ckpt_path.exists() else None
    if not ckpt:
        # Sometimes nested under production/
        alt = root / "production" / "checkpoint.json"
        ckpt = _load_json(alt) if alt.exists() else None
        if ckpt:
            ckpt_path = alt

    if ckpt and ckpt.get("status") in ("aborted", "failed"):
        # Check graph_state.json for the broken run_id="unknown" pattern
        gs = _load_json(root / "graph_state.json") or {}
        bad_graph = gs.get("run_id") == "unknown" or gs.get("current_phase") == "not_started"

        # Check whether any alert / signal was emitted
        alert_files = list(root.rglob("alert*.json")) + list(root.rglob("incident*.json"))

        out.append(Finding(
            code="F1_silent_abort",
            severity="critical",
            message=f"checkpoint.status={ckpt['status']} at {ckpt.get('updated_at','?')} "
                    f"but no alert artifact emitted and graph_state {'broken' if bad_graph else 'ok'}",
            evidence={
                "checkpoint_status": ckpt.get("status"),
                "checkpoint_updated_at": ckpt.get("updated_at"),
                "phases_completed": sum(
                    1 for p in (ckpt.get("phases") or {}).values()
                    if isinstance(p, dict) and p.get("status") == "completed"
                ),
                "graph_state_broken": bad_graph,
                "graph_state_run_id": gs.get("run_id"),
                "alert_artifacts": [str(p.relative_to(root)) for p in alert_files],
            },
            suggested_action=(
                "Dispatch resume polecat: `gt nudge contentx-shorts/resume --run-id="
                + ckpt.get("run_id", "?") + "`"
            ),
        ))
    return out


def detect_f2_gate_fail_but_ship(root: Path) -> list[Finding]:
    """F2 — quality/*.passed=false but publish artifacts present."""
    out: list[Finding] = []
    quality_dirs = list(root.rglob("quality"))
    failed: list[tuple[Path, dict[str, Any]]] = []
    for qd in quality_dirs:
        if not qd.is_dir():
            continue
        for f in qd.glob("*.json"):
            data = _load_json(f)
            if isinstance(data, dict) and data.get("passed") is False:
                failed.append((f, data))

    # Did the run ship?
    publish_signals = (
        list(root.rglob("publish_metadata.json"))
        + list(root.rglob("distribution"))
        + list(root.rglob("final_video*.mp4"))
    )
    shipped = bool(publish_signals)

    for fp, data in failed:
        out.append(Finding(
            code="F2_gate_fail_but_ship",
            severity="blocker" if shipped else "critical",
            message=(
                f"{fp.relative_to(root)} reports passed=false "
                f"({len(data.get('issues') or [])} issues) "
                f"{'AND publish artifacts exist — failed asset shipped' if shipped else 'but no publish yet (acceptable)'}"
            ),
            evidence={
                "gate_file": str(fp.relative_to(root)),
                "issues": (data.get("issues") or [])[:5],
                "publish_signals": [str(p.relative_to(root)) for p in publish_signals[:5]],
                "shipped": shipped,
            },
            suggested_action=(
                "Refinery refuses MR; route bead to audio/qc polecat with the failed gate"
                if shipped else "Block downstream publish until passed=true"
            ),
        ))

    # F2b: guard_summary shows zero checks ran
    guard_files = list(root.rglob("guard_summary.json"))
    for g in guard_files:
        gd = _load_json(g) or {}
        if gd.get("total_checks", -1) == 0:
            out.append(Finding(
                code="F2b_guard_not_run",
                severity="critical",
                message=f"{g.relative_to(root)} reports total_checks=0 — gate never executed",
                evidence={"file": str(g.relative_to(root)), "contents": gd},
                suggested_action="Wire guard invocation into the pipeline phase before delivery",
            ))
    return out


def detect_f3_council_unapplied(root: Path) -> list[Finding]:
    """F3 — council audits have directives but redo_count=0 and approved_output=null."""
    out: list[Finding] = []
    for ca in root.rglob("council_audits"):
        if not ca.is_dir():
            continue
        for f in ca.glob("*_audit.json"):
            data = _load_json(f)
            if not isinstance(data, dict):
                continue
            verdict = data.get("final_verdict") or data.get("quality_verdict")
            directives = data.get("directives") or []
            redo = int(data.get("redo_count") or 0)
            max_redos = int(data.get("max_redos") or 0)
            approved = data.get("approved_output")
            if verdict in ("FAIL", "PASS_WITH_NOTES") and len(directives) > 0 and redo == 0:
                out.append(Finding(
                    code="F3_council_unapplied",
                    severity="critical" if verdict == "FAIL" else "high",
                    message=(
                        f"{f.relative_to(root)} verdict={verdict} with {len(directives)} directives, "
                        f"redo_count=0/{max_redos}, approved_output={approved}"
                    ),
                    evidence={
                        "audit_file": str(f.relative_to(root)),
                        "verdict": verdict,
                        "n_directives": len(directives),
                        "directives_preview": [str(d)[:120] for d in directives[:5]],
                        "max_redos": max_redos,
                        "quality_score": data.get("quality_score"),
                    },
                    suggested_action=(
                        f"Spawn {min(len(directives), max_redos or 1)} redo subagents, "
                        f"one bd per directive parented to run-bead"
                    ),
                ))
    return out


def detect_f4_blocker_silenced(root: Path) -> list[Finding]:
    """F4 — gap_reports declare blockers but pipeline progressed."""
    out: list[Finding] = []
    blockers_seen = 0
    for gr_dir in root.rglob("gap_reports"):
        if not gr_dir.is_dir():
            continue
        for f in gr_dir.glob("*_gap_report.json"):
            data = _load_json(f)
            if not isinstance(data, dict):
                continue
            for gap in data.get("gaps", []) or []:
                if (gap.get("severity") or "").lower() == "blocker":
                    blockers_seen += 1
                    out.append(Finding(
                        code="F4_blocker_silenced",
                        severity="blocker",
                        message=f"blocker `{gap.get('code')}` in {f.relative_to(root)} — {gap.get('message')}",
                        evidence={
                            "gap_file": str(f.relative_to(root)),
                            "blocker_code": gap.get("code"),
                            "blocker_phase": gap.get("phase"),
                            "blocker_message": gap.get("message"),
                            "suggested_remediation": gap.get("suggestion"),
                        },
                        suggested_action=(
                            f"gt escalate --severity=CRITICAL --route=mayor "
                            f"'gap_{gap.get('code')} in {gap.get('phase')} unaddressed'"
                        ),
                    ))
    return out


def detect_f5_open_feedback(root: Path) -> list[Finding]:
    """F5 — run_feedback.json is a stub with no closure."""
    out: list[Finding] = []
    for f in root.rglob("run_feedback.json"):
        data = _load_json(f)
        if not isinstance(data, dict):
            continue
        engagement = data.get("signals", {}).get("engagement_metrics") or data.get("engagement_metrics")
        empty = (
            data.get("status") == "needs_review"
            and not (engagement or {})
            and not (data.get("actions") or [])
            and not data.get("notes")
        )
        if empty:
            out.append(Finding(
                code="F5_open_feedback",
                severity="medium",
                message=f"{f.relative_to(root)} is an unclosed stub — no engagement metrics, no actions, no notes",
                evidence={"file": str(f.relative_to(root)), "status": data.get("status")},
                suggested_action=(
                    "Migrate to bead: `bd create --type=feedback --parent=<run-bead> "
                    "--title='run_feedback for <run_id>' --status=open`. "
                    "Update from Postiz webhook + browser_provider scrape at +24h/+72h/+7d."
                ),
            ))
    return out


def detect_f6_nested_duplication(root: Path) -> list[Finding]:
    """F6 — same-named JSON state files duplicated under nested production paths."""
    out: list[Finding] = []
    state_files = (
        "brand_colors.json", "voice_registry.json", "voice_assignments.json",
        "voice_mapping.json", "voiceover_memory.json", "studio_bible.json",
        "weather_state.json", "clothing_state.json", "character_aging.json",
        "story_arc.json", "visual_aid_style.json", "dialogue_history.json",
        "production_artifacts.json", "production_graph.json",
        "production_graph_viz.json", "production_state.json",
    )
    duplicates: dict[str, list[Path]] = {}
    total_bytes_wasted = 0
    for name in state_files:
        copies = list(root.rglob(name))
        if len(copies) > 1:
            # Hash to find actual duplicates
            hashes: dict[str, list[Path]] = {}
            for c in copies:
                try:
                    h = hashlib.md5(c.read_bytes()).hexdigest()
                    hashes.setdefault(h, []).append(c)
                except OSError:
                    continue
            for h, paths in hashes.items():
                if len(paths) > 1:
                    duplicates[name] = paths
                    sizes = [p.stat().st_size for p in paths[1:]]
                    total_bytes_wasted += sum(sizes)

    if duplicates:
        # Also count nested dirs like production/production/
        nested_prods = list(root.rglob("production/production"))
        out.append(Finding(
            code="F6_nested_duplication",
            severity="high",
            message=(
                f"{len(duplicates)} state-file types duplicated across nested paths "
                f"({sum(len(v) for v in duplicates.values())} copies, "
                f"~{total_bytes_wasted/1024:.0f} KB wasted)"
            ),
            evidence={
                "duplicate_types": list(duplicates.keys()),
                "examples": {
                    name: [str(p.relative_to(root)) for p in paths]
                    for name, paths in list(duplicates.items())[:3]
                },
                "nested_production_dirs": [str(p.relative_to(root)) for p in nested_prods],
                "bytes_wasted_approx": total_bytes_wasted,
            },
            suggested_action=(
                "Run `run_id_repairer.py --fix=F6 <run_path>` — "
                "canonicalize state files at root, symlink scene copies."
            ),
        ))
    return out


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def compute_stats(root: Path) -> dict[str, Any]:
    total_bytes = 0
    file_count = 0
    for p in root.rglob("*"):
        if p.is_file():
            file_count += 1
            try:
                total_bytes += p.stat().st_size
            except OSError:
                continue
    return {
        "total_files": file_count,
        "total_mb": round(total_bytes / 1024 / 1024, 1),
    }


# ---------------------------------------------------------------------------
# Top-level audit
# ---------------------------------------------------------------------------

def audit_run(run_path: Path) -> RunAudit:
    run_id = run_path.name
    run_json = _load_json(run_path / "run.json") or {}
    pipeline_kind = run_json.get("pipeline")

    audit = RunAudit(run_id=run_id, run_path=str(run_path), pipeline_kind=pipeline_kind)
    audit.findings.extend(detect_f1_silent_abort(run_path))
    audit.findings.extend(detect_f2_gate_fail_but_ship(run_path))
    audit.findings.extend(detect_f3_council_unapplied(run_path))
    audit.findings.extend(detect_f4_blocker_silenced(run_path))
    audit.findings.extend(detect_f5_open_feedback(run_path))
    audit.findings.extend(detect_f6_nested_duplication(run_path))
    audit.stats = compute_stats(run_path)
    return audit


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

SEVERITY_WEIGHT = {"blocker": 20, "critical": 10, "high": 5, "medium": 2, "low": 1}


def health_score(audit: RunAudit) -> dict[str, Any]:
    weighted = sum(SEVERITY_WEIGHT.get(f.severity, 1) for f in audit.findings)
    grade = "A"
    if weighted > 0:
        grade = "B"
    if weighted >= 5:
        grade = "C"
    if weighted >= 15:
        grade = "D"
    if weighted >= 30:
        grade = "F"
    return {"weighted_defect_score": weighted, "grade": grade}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="run folder or parent dir")
    ap.add_argument("--batch", help="parent dir containing multiple runs")
    ap.add_argument("--out", help="write JSON report to file")
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout")
    args = ap.parse_args()

    target = args.batch or args.path
    if not target:
        ap.print_help()
        sys.exit(2)

    target_path = Path(target).expanduser().resolve()
    if not target_path.exists():
        print(f"error: {target_path} does not exist", file=sys.stderr)
        sys.exit(1)

    if args.batch:
        runs = [p for p in target_path.iterdir() if p.is_dir() and not p.name.startswith(".")]
        audits = [audit_run(r) for r in runs]
        report = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "batch_root": str(target_path),
            "total_runs": len(audits),
            "runs": [{**a.to_dict(), **{"health": health_score(a)}} for a in audits],
            "aggregate": {
                "by_code": _aggregate_codes(audits),
                "by_grade": _aggregate_grades(audits),
                "runs_with_findings": sum(1 for a in audits if a.findings),
            },
        }
    else:
        audit = audit_run(target_path)
        report = {**audit.to_dict(), **{"health": health_score(audit)}}

    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"report -> {args.out}")
    if args.json or not args.out:
        if args.json:
            print(text)
        else:
            _print_human_summary(report)


def _aggregate_codes(audits: list[RunAudit]) -> dict[str, int]:
    agg: dict[str, int] = {}
    for a in audits:
        for f in a.findings:
            agg[f.code] = agg.get(f.code, 0) + 1
    return dict(sorted(agg.items(), key=lambda x: -x[1]))


def _aggregate_grades(audits: list[RunAudit]) -> dict[str, int]:
    agg: dict[str, int] = {}
    for a in audits:
        g = health_score(a)["grade"]
        agg[g] = agg.get(g, 0) + 1
    return dict(sorted(agg.items()))


def _print_human_summary(report: dict[str, Any]) -> None:
    if "runs" in report:
        print(f"\nBatch audit: {report['total_runs']} runs at {report['batch_root']}")
        print(f"  runs with findings: {report['aggregate']['runs_with_findings']}")
        print(f"  by grade: {report['aggregate']['by_grade']}")
        print(f"  by code: {report['aggregate']['by_code']}")
        print("\nWorst runs:")
        sorted_runs = sorted(report["runs"], key=lambda r: -r["health"]["weighted_defect_score"])
        for r in sorted_runs[:5]:
            print(f"  [{r['health']['grade']}/{r['health']['weighted_defect_score']:>3}] {r['run_id']}  ({r['summary']['total']} findings, {r['stats']['total_mb']:.0f} MB)")
            for code, count in r["summary"]["by_code"].items():
                print(f"        {code}: {count}")
    else:
        print(f"\nrun_id: {report['run_id']}")
        print(f"  pipeline: {report['pipeline_kind']}")
        print(f"  size: {report['stats']['total_mb']:.0f} MB / {report['stats']['total_files']} files")
        print(f"  grade: {report['health']['grade']} (defect score {report['health']['weighted_defect_score']})")
        print(f"  findings: {report['summary']['total']}")
        for f in report["findings"]:
            print(f"    [{f['severity']:<8}] {f['code']}: {f['message']}")


if __name__ == "__main__":
    main()
