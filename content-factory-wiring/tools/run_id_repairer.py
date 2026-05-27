"""
run_id_repairer.py — turn auditor findings into Gas Town actions.

Reads a JSON audit report from run_id_auditor.py and emits, for each finding:

  • A bd-create or gt-escalate command
  • A repair script for F6 (canonicalize duplicates)
  • A signed alert artifact for F1
  • A run_feedback bead migration for F5

Modes:
  --dry-run        : print commands, don't execute (default)
  --apply          : execute the bd/gt/file actions
  --fix=F6         : actually rewrite duplicates → symlinks for one mode
  --emit-beads     : write beads.jsonl ready for `bd import`
  --emit-script    : write a bash script with all gt/bd commands
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")[:48]


def f1_actions(run_id: str, finding: dict) -> list[dict]:
    return [
        {
            "kind": "alert_artifact",
            "path": f"{run_id}/alerts/silent_abort.json",
            "body": {
                "run_id": run_id,
                "alert_type": "silent_abort",
                "raised_at": datetime.now(timezone.utc).isoformat(),
                "checkpoint_status": finding["evidence"].get("checkpoint_status"),
                "evidence": finding["evidence"],
            },
        },
        {
            "kind": "gt_command",
            "cmd": f"gt nudge contentx-shorts/resume --bead qv-run-{slug(run_id)} -m 'silent abort, please resume'",
        },
        {
            "kind": "bd_create",
            "args": {
                "type": "bug",
                "priority": 1,
                "title": f"Resume aborted run {run_id}",
                "labels": ["content-factory", "resume", "F1"],
                "body": (
                    f"Pipeline aborted silently at "
                    f"{finding['evidence'].get('checkpoint_updated_at')} after "
                    f"{finding['evidence'].get('phases_completed', '?')} completed phases. "
                    f"No alert artifact was emitted. Polecat should boot, "
                    f"read checkpoint.json, restart from last incomplete phase."
                ),
            },
        },
    ]


def f2_actions(run_id: str, finding: dict) -> list[dict]:
    return [
        {
            "kind": "gt_command",
            "cmd": (
                f"gt sling reject {finding['evidence']['gate_file']} "
                f"--run={run_id} --reason='gate passed=false but shipped'"
            ),
        },
        {
            "kind": "bd_create",
            "args": {
                "type": "bug",
                "priority": 1,
                "title": f"Gate-fail-but-ship: {finding['evidence']['gate_file']}",
                "labels": ["content-factory", "refinery", "F2"],
                "body": (
                    f"Quality gate {finding['evidence']['gate_file']} reported "
                    f"passed=false but publish artifacts exist. "
                    f"Issues: {finding['evidence'].get('issues')}"
                ),
            },
        },
    ]


def f2b_actions(run_id: str, finding: dict) -> list[dict]:
    return [
        {
            "kind": "bd_create",
            "args": {
                "type": "bug",
                "priority": 1,
                "title": f"Guard never executed in {run_id}",
                "labels": ["content-factory", "refinery", "F2b"],
                "body": (
                    f"guard_summary.json reports total_checks=0 — the guard was "
                    f"declared but never invoked. Wire `guard.run_all()` "
                    f"into the delivery phase before final_video assembly."
                ),
            },
        },
    ]


def f3_actions(run_id: str, finding: dict) -> list[dict]:
    """Council audit had N directives, none applied → 1 bd per directive."""
    out: list[dict] = []
    parent = f"qv-run-{slug(run_id)}"
    audit_file = finding["evidence"]["audit_file"]
    directives = finding["evidence"].get("directives_preview", [])
    for i, d in enumerate(directives):
        out.append({
            "kind": "bd_create",
            "args": {
                "type": "fix",
                "priority": 2,
                "title": f"[{run_id}] directive {i+1}/{len(directives)}: {d[:80]}",
                "labels": ["content-factory", "council-directive", "F3"],
                "parent": parent,
                "body": (
                    f"Council audit {audit_file} verdict={finding['evidence']['verdict']} "
                    f"recommended this directive but redo_count=0 (max_redos="
                    f"{finding['evidence']['max_redos']}). Apply via redo subagent."
                ),
            },
        })
    if len(finding["evidence"].get("directives_preview") or []) >= 5:
        out.append({
            "kind": "gt_command",
            "cmd": (
                f"gt convoy create --type=mountain --parent={parent} "
                f"--name='apply-directives-{slug(audit_file)}' "
                f"--max-concurrent=3 --sla-hours=2"
            ),
        })
    return out


def f4_actions(run_id: str, finding: dict) -> list[dict]:
    code = finding["evidence"]["blocker_code"]
    return [
        {
            "kind": "gt_command",
            "cmd": (
                f"gt escalate --severity=CRITICAL --route=mayor "
                f"--bead=qv-run-{slug(run_id)} "
                f"'blocker {code} ignored in phase {finding['evidence']['blocker_phase']}'"
            ),
        },
        {
            "kind": "bd_create",
            "args": {
                "type": "bug",
                "priority": 0,
                "title": f"P0: blocker `{code}` silenced in {run_id}",
                "labels": ["content-factory", "escalation", "F4"],
                "body": (
                    f"Gap report flagged blocker `{code}` with suggestion: "
                    f"{finding['evidence'].get('suggested_remediation')}. Pipeline progressed past."
                ),
            },
        },
    ]


def f5_actions(run_id: str, finding: dict) -> list[dict]:
    return [
        {
            "kind": "bd_create",
            "args": {
                "type": "feedback",
                "priority": 3,
                "title": f"Engagement feedback for {run_id}",
                "labels": ["content-factory", "feedback-loop", "F5"],
                "parent": f"qv-run-{slug(run_id)}",
                "status": "open",
                "body": (
                    f"Migrated from {finding['evidence']['file']}. "
                    f"Will be updated by Postiz webhook + browser_provider scrape "
                    f"at +24h/+72h/+7d post-publish. Closing this bead = run learned from."
                ),
            },
        },
        {
            "kind": "cron_entry",
            "schedule": "0 */6 * * *",  # every 6h
            "command": (
                f"contentx-engagement-scrape --run-id={run_id} "
                f"--bead=qv-run-{slug(run_id)} --max-age-days=7"
            ),
        },
    ]


def f6_actions(run_id: str, finding: dict, run_path: Path, apply: bool) -> list[dict]:
    """For F6 we can actually fix it: keep root copies, replace nested with symlinks."""
    out: list[dict] = []
    examples = finding["evidence"].get("examples", {})
    actions_planned = []
    for state_name, paths_rel in examples.items():
        # First path is canonical (assume root-most); others become symlinks
        sorted_paths = sorted(paths_rel, key=lambda p: p.count("/"))
        canon = sorted_paths[0]
        for dup in sorted_paths[1:]:
            actions_planned.append({"keep": canon, "symlink": dup})
    out.append({
        "kind": "file_dedup_plan",
        "run_path": str(run_path),
        "plan": actions_planned,
        "applied": False,
    })

    if apply and run_path.exists():
        applied: list[dict] = []
        for act in actions_planned:
            canon_abs = run_path / act["keep"]
            dup_abs = run_path / act["symlink"]
            if not canon_abs.exists() or not dup_abs.exists():
                continue
            if dup_abs.is_symlink():
                continue
            try:
                dup_abs.unlink()
                rel_canon = os.path.relpath(canon_abs, dup_abs.parent)
                dup_abs.symlink_to(rel_canon)
                applied.append({"symlinked": str(dup_abs), "to": rel_canon})
            except OSError as exc:
                applied.append({"failed": str(dup_abs), "error": str(exc)})
        out[-1]["applied"] = True
        out[-1]["applied_actions"] = applied
    return out


# ---------------------------------------------------------------------------

def repair(audit: dict, run_path: Path | None, *, apply_f6: bool = False) -> dict:
    run_id = audit["run_id"]
    actions: list[dict] = []
    handlers = {
        "F1_silent_abort": lambda f: f1_actions(run_id, f),
        "F2_gate_fail_but_ship": lambda f: f2_actions(run_id, f),
        "F2b_guard_not_run": lambda f: f2b_actions(run_id, f),
        "F3_council_unapplied": lambda f: f3_actions(run_id, f),
        "F4_blocker_silenced": lambda f: f4_actions(run_id, f),
        "F5_open_feedback": lambda f: f5_actions(run_id, f),
    }
    for finding in audit["findings"]:
        code = finding["code"]
        if code in handlers:
            actions.extend(handlers[code](finding))
        elif code == "F6_nested_duplication" and run_path:
            actions.extend(f6_actions(run_id, finding, run_path, apply=apply_f6))
    return {
        "run_id": run_id,
        "actions": actions,
        "summary": _summarize(actions),
        "repaired_at": datetime.now(timezone.utc).isoformat(),
    }


def _summarize(actions: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in actions:
        out[a["kind"]] = out.get(a["kind"], 0) + 1
    return out


# ---------------------------------------------------------------------------

def emit_beads(repair_result: dict, out_path: Path) -> int:
    n = 0
    with out_path.open("w") as fh:
        for a in repair_result["actions"]:
            if a["kind"] == "bd_create":
                fh.write(json.dumps(a["args"]) + "\n")
                n += 1
    return n


TYPE_MAP = {"fix": "bug", "feedback": "task", "alert": "bug"}


def _bd_cmd(args: dict) -> str:
    """Translate our internal bd args into the real bd CLI syntax."""
    btype = TYPE_MAP.get(args.get("type"), args.get("type", "task"))
    if btype not in ("bug", "feature", "task", "epic", "chore", "decision"):
        btype = "task"
    cmd = f'bd create {json.dumps(args["title"])} --type={btype} --priority={args["priority"]}'
    if "labels" in args:
        cmd += " --labels=" + ",".join(args["labels"])
    if "parent" in args:
        cmd += f" --parent={args['parent']}"
    desc = args.get("description") or args.get("body") or ""
    if desc:
        cmd += " --description=" + json.dumps(desc)
    return cmd


def emit_script(repair_result: dict, out_path: Path) -> int:
    lines = [
        "#!/usr/bin/env bash",
        "# Auto-generated by run_id_repairer.py",
        f"# repair for run_id: {repair_result['run_id']}",
        "# Requires: bd installed (`go install github.com/steveyegge/beads/cmd/bd@latest`)",
        "#           and gt CLI present in PATH",
        "set -euo pipefail",
        "",
    ]
    n = 0
    for a in repair_result["actions"]:
        if a["kind"] == "bd_create":
            lines.append(_bd_cmd(a["args"]))
            n += 1
        elif a["kind"] == "gt_command":
            lines.append(_translate_gt(a["cmd"]))
            n += 1
        elif a["kind"] == "cron_entry":
            lines.append(f"# cron: {a['schedule']}  {a['command']}")
    out_path.write_text("\n".join(lines) + "\n")
    out_path.chmod(0o755)
    return n


def _translate_gt(cmd: str) -> str:
    """Map our pseudo-gt commands into real gt CLI subcommands."""
    # gt nudge X -m "msg"     →  gt assign mayor "msg" --label=nudge-X
    if cmd.startswith("gt nudge "):
        m = re.match(r"gt nudge (\S+)(?:\s+--bead=(\S+))?(?:\s+-m\s+(.+))?", cmd)
        if m:
            target, bead, msg = m.group(1), m.group(2), m.group(3) or ""
            return f'gt assign mayor "[nudge {target}] {msg.strip(chr(39)+chr(34))}"'
    # gt escalate --severity=CRITICAL --route=mayor "msg"  →  bd create … P0
    if cmd.startswith("gt escalate "):
        m = re.search(r"--severity=(\w+)", cmd)
        sev = (m.group(1) if m else "HIGH").upper()
        priority = {"CRITICAL": "0", "BLOCKER": "0", "HIGH": "1", "MEDIUM": "2"}.get(sev, "1")
        msg_m = re.search(r"['\"]([^'\"]+)['\"]\s*$", cmd)
        msg = msg_m.group(1) if msg_m else cmd.replace("gt escalate ", "")
        return f'bd create "P{priority} ESCALATION: {msg}" --type=bug --priority={priority} --labels=escalation,content-factory'
    # gt sling reject X      →  bd create … blocker
    if cmd.startswith("gt sling reject "):
        m = re.match(r"gt sling reject (\S+).*--run=(\S+).*--reason=['\"]([^'\"]+)['\"]", cmd)
        if m:
            gate, run, reason = m.groups()
            return f'bd create "Sling rejected: {gate} ({reason})" --type=bug --priority=0 --labels=content-factory,refinery,sling-reject'
    # gt convoy create        →  bd create epic
    if cmd.startswith("gt convoy create "):
        title_m = re.search(r"--name=['\"]?([^'\"]+)['\"]?", cmd)
        title = title_m.group(1) if title_m else "convoy"
        return f'bd create "Convoy: {title}" --type=epic --priority=2 --labels=content-factory,convoy'
    return f'# UNKNOWN: {cmd}'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audit_json")
    ap.add_argument("--run-path", help="absolute path to the run folder (needed for F6 fix)")
    ap.add_argument("--apply-f6", action="store_true", help="actually symlink duplicate state files")
    ap.add_argument("--emit-beads", help="write beads.jsonl")
    ap.add_argument("--emit-script", help="write bash script")
    ap.add_argument("--out", help="write full repair plan JSON")
    args = ap.parse_args()

    audit = json.loads(Path(args.audit_json).read_text())
    if "runs" in audit:
        # batch
        all_repairs: list[dict] = []
        for r in audit["runs"]:
            rp = Path(r["run_path"]) if r.get("run_path") else None
            all_repairs.append(repair(r, rp, apply_f6=args.apply_f6))
        full = {"batch_repair": True, "repairs": all_repairs}
    else:
        rp = Path(args.run_path) if args.run_path else Path(audit.get("run_path", ""))
        full = repair(audit, rp if rp.exists() else None, apply_f6=args.apply_f6)

    if args.out:
        Path(args.out).write_text(json.dumps(full, indent=2))
        print(f"plan -> {args.out}")

    if args.emit_beads:
        out_path = Path(args.emit_beads)
        if "batch_repair" in full:
            with out_path.open("w") as fh:
                for r in full["repairs"]:
                    for a in r["actions"]:
                        if a["kind"] == "bd_create":
                            fh.write(json.dumps(a["args"]) + "\n")
        else:
            emit_beads(full, out_path)
        print(f"beads -> {args.emit_beads}")

    if args.emit_script:
        out_path = Path(args.emit_script)
        if "batch_repair" in full:
            lines = [
                "#!/usr/bin/env bash",
                "# Auto-generated by run_id_repairer.py (batch)",
                "# Requires: bd installed (`go install github.com/steveyegge/beads/cmd/bd@latest`)",
                "set -euo pipefail",
                "",
            ]
            for r in full["repairs"]:
                lines.append(f"# === {r['run_id']} ===")
                for a in r["actions"]:
                    if a["kind"] == "bd_create":
                        lines.append(_bd_cmd(a["args"]))
                    elif a["kind"] == "gt_command":
                        lines.append(_translate_gt(a["cmd"]))
                lines.append("")
            out_path.write_text("\n".join(lines))
            out_path.chmod(0o755)
        else:
            emit_script(full, out_path)
        print(f"script -> {args.emit_script}")

    if "batch_repair" in full:
        total_actions = sum(len(r["actions"]) for r in full["repairs"])
        print(f"\nBatch repair plan: {len(full['repairs'])} runs, {total_actions} actions")
        agg: dict[str, int] = {}
        for r in full["repairs"]:
            for k, v in r["summary"].items():
                agg[k] = agg.get(k, 0) + v
        for k, v in sorted(agg.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
    else:
        print(f"\nRepair plan for {full['run_id']}:")
        for k, v in full["summary"].items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
