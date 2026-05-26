"""
kpi_tracker.py — measure content-factory vs. its own MEMORY_FEEDBACK_LOOP_IMPACT targets.

Pulls live data from the Hermes SessionDB + the latest run audit and emits
a markdown digest, JSON snapshot, and Prometheus metrics file.

Compares observed to the team's own predicted KPI table:
    Cross-channel script repeat rate    12% -> <2%
    Weighted 30s retention (Shorts)     38% -> 48-53%
    Approved publishes / week           18  -> 55-70
    Voice continuity audited            manual -> 100%
    Off-brand publish slip-through      ~5% -> <0.5%
    Council directive apply rate        0% (today) -> 100%
    Silent-abort rate                   ~89% (today) -> <1%
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


KPI_TARGETS = {
    "council_directive_apply_rate":      {"baseline": 0.00, "t30d": 0.50, "t90d": 0.95, "unit": "ratio"},
    "silent_abort_rate":                 {"baseline": 0.89, "t30d": 0.10, "t90d": 0.01, "unit": "ratio"},
    "blocker_gaps_silenced_rate":        {"baseline": 1.00, "t30d": 0.10, "t90d": 0.00, "unit": "ratio"},
    "audio_gate_compliance":             {"baseline": 0.00, "t30d": 0.80, "t90d": 1.00, "unit": "ratio"},
    "guard_actually_ran":                {"baseline": 0.11, "t30d": 1.00, "t90d": 1.00, "unit": "ratio"},
    "feedback_loop_closure_rate":        {"baseline": 0.00, "t30d": 0.50, "t90d": 0.95, "unit": "ratio"},
    "script_repeat_rate":                {"baseline": 0.12, "t30d": 0.05, "t90d": 0.02, "unit": "ratio"},
    "approved_publishes_per_week":       {"baseline": 18,   "t30d": 32,   "t90d": 60,   "unit": "count"},
    "off_brand_slip_through":            {"baseline": 0.05, "t30d": 0.01, "t90d": 0.005, "unit": "ratio"},
    "mean_size_per_run_mb":              {"baseline": 490,  "t30d": 200,  "t90d": 50,   "unit": "mb"},
    "weighted_defect_score_avg":         {"baseline": 220,  "t30d": 50,   "t90d": 5,    "unit": "score"},
}


def measure(db_path: Path, audit_json: Path | None) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    conn = sqlite3.connect(db_path) if db_path.exists() else None

    if conn:
        # council_directive_apply_rate
        total_d, applied_d = conn.execute(
            "SELECT COUNT(*), SUM(applied) FROM directives"
        ).fetchone()
        metrics["council_directive_apply_rate"] = (
            (applied_d or 0) / total_d if total_d else 0.0
        )

        # blocker_gaps_silenced_rate
        total_g = conn.execute(
            "SELECT COUNT(*) FROM gaps WHERE severity='blocker'"
        ).fetchone()[0]
        resolved_g = conn.execute(
            "SELECT COUNT(*) FROM gaps WHERE severity='blocker' AND resolved=1"
        ).fetchone()[0]
        metrics["blocker_gaps_silenced_rate"] = (
            (total_g - resolved_g) / total_g if total_g else 0.0
        )

        # feedback_loop_closure_rate (proxy: % runs with engagement rows)
        n_runs = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        n_with_eng = conn.execute(
            "SELECT COUNT(DISTINCT run_id) FROM engagement"
        ).fetchone()[0]
        metrics["feedback_loop_closure_rate"] = (
            n_with_eng / n_runs if n_runs else 0.0
        )

        # approved_publishes_per_week
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        approved = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE status='completed' AND ended_at >= ?",
            (week_ago,),
        ).fetchone()[0]
        metrics["approved_publishes_per_week"] = approved

    if audit_json and audit_json.exists():
        report = json.loads(audit_json.read_text())
        runs = report.get("runs") or [report]
        n = len(runs)
        # silent_abort_rate
        silent = sum(
            1 for r in runs if any(f["code"] == "F1_silent_abort" for f in r["findings"])
        )
        metrics["silent_abort_rate"] = silent / n if n else 0.0
        # audio_gate_compliance
        audio_fail = sum(
            1 for r in runs if any(f["code"] == "F2_gate_fail_but_ship" for f in r["findings"])
        )
        metrics["audio_gate_compliance"] = 1 - (audio_fail / n) if n else 0.0
        # guard_actually_ran
        guard_skipped = sum(
            1 for r in runs if any(f["code"] == "F2b_guard_not_run" for f in r["findings"])
        )
        metrics["guard_actually_ran"] = 1 - (guard_skipped / n) if n else 0.0
        # mean_size_per_run_mb
        sizes = [r["stats"]["total_mb"] for r in runs if "stats" in r]
        metrics["mean_size_per_run_mb"] = sum(sizes) / len(sizes) if sizes else 0.0
        # weighted_defect_score_avg
        scores = [r["health"]["weighted_defect_score"] for r in runs if "health" in r]
        metrics["weighted_defect_score_avg"] = sum(scores) / len(scores) if scores else 0.0

    return metrics


def render_markdown(metrics: dict[str, Any]) -> str:
    lines = ["# ContentX KPI Tracker — Weekly Digest", "",
             f"_Generated: {datetime.now(timezone.utc).isoformat()}_", "",
             "| Metric | Baseline | Today | T+30d target | T+90d target | Status |",
             "|---|---:|---:|---:|---:|:---:|"]
    for key, target in KPI_TARGETS.items():
        today = metrics.get(key)
        baseline = target["baseline"]
        t30 = target["t30d"]
        t90 = target["t90d"]
        # Direction: lower-is-better for rates >= 0.01
        lower_better = key in {
            "silent_abort_rate", "blocker_gaps_silenced_rate",
            "script_repeat_rate", "off_brand_slip_through",
            "mean_size_per_run_mb", "weighted_defect_score_avg",
        }
        if today is None:
            status = "—"
        elif lower_better:
            status = "✅" if today <= t30 else "❌"
        else:
            status = "✅" if today >= t30 else "❌"
        fmt = lambda v: (
            f"{v:.0%}" if target["unit"] == "ratio" and v is not None
            else f"{v:.0f}" if v is not None else "—"
        )
        lines.append(f"| `{key}` | {fmt(baseline)} | {fmt(today)} | {fmt(t30)} | {fmt(t90)} | {status} |")
    lines.append("")
    lines.append("## What this means")
    fail = sum(1 for k, t in KPI_TARGETS.items()
               if metrics.get(k) is not None
               and ((k in {"silent_abort_rate","blocker_gaps_silenced_rate","script_repeat_rate","off_brand_slip_through","mean_size_per_run_mb","weighted_defect_score_avg"}
                     and metrics[k] > t["t30d"])
                    or (k not in {"silent_abort_rate","blocker_gaps_silenced_rate","script_repeat_rate","off_brand_slip_through","mean_size_per_run_mb","weighted_defect_score_avg"}
                        and metrics[k] < t["t30d"])))
    lines.append(f"")
    lines.append(f"- **{fail}** KPIs missing the T+30d target.")
    lines.append(f"- Drilldowns: `bd list --labels=content-factory --status=open --priority=0,1`")
    return "\n".join(lines)


def render_prom(metrics: dict[str, Any]) -> str:
    lines = []
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            lines.append(f"contentx_{k} {v}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="reports/hermes_contentx.sqlite")
    ap.add_argument("--audit", default="reports/batch_audit_video.json")
    ap.add_argument("--out", default="reports/kpi_digest.md")
    ap.add_argument("--prom", default=None, help="write Prometheus textfile")
    ap.add_argument("--weekly", action="store_true")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent.parent
    db = (here / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db)
    audit = (here / args.audit).resolve() if not Path(args.audit).is_absolute() else Path(args.audit)

    metrics = measure(db, audit)
    md = render_markdown(metrics)
    Path(args.out).write_text(md)
    print(md)
    if args.prom:
        Path(args.prom).write_text(render_prom(metrics))


if __name__ == "__main__":
    main()
