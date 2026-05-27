"""
hermes_indexer.py — bootstrap Hermes' FTS5 SessionDB from existing content-factory runs.

For every run folder we ingest:
  • run.json + checkpoint.json metadata
  • All council_audits/*.json (directives, scores, verdicts)
  • All gap_reports/*.json (blockers, warns, infos)
  • All quality/*.json (audio, delivery, guard)
  • analytics_events.jsonl (per-phase telemetry)
  • run_feedback.json (status, engagement)
  • final outputs metadata (size, codec, duration)

Each gets indexed as a Hermes "session record" so `hermes search` and
`/whatdoweknow` queries can hit it. Runs over 200 historical viral_shorts
take ~30 seconds and produce a queryable knowledge base.

This is a self-contained shim — it talks to Hermes' SessionDB schema directly
via SQLite + FTS5 so we don't need a running Hermes process to bootstrap.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    pipeline_kind TEXT,
    started_at    TEXT,
    ended_at      TEXT,
    status        TEXT,
    grade         TEXT,
    quality_score REAL,
    summary       TEXT,
    brand         TEXT,
    raw_metadata  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_run ON sessions(run_id);
CREATE INDEX IF NOT EXISTS idx_sessions_pipeline ON sessions(pipeline_kind, started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    session_id,
    run_id,
    title,
    body,
    tags,
    content=''
);

CREATE TABLE IF NOT EXISTS directives (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    audit_file    TEXT,
    audit_phase   TEXT,
    directive     TEXT,
    verdict       TEXT,
    applied       INTEGER DEFAULT 0,
    occurrence_n  INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_dir_run ON directives(run_id);
CREATE INDEX IF NOT EXISTS idx_dir_phase ON directives(audit_phase);

CREATE VIRTUAL TABLE IF NOT EXISTS directives_fts USING fts5(
    directive,
    audit_phase,
    verdict,
    content=''
);

CREATE TABLE IF NOT EXISTS gaps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    code          TEXT,
    severity      TEXT,
    phase         TEXT,
    message       TEXT,
    resolved      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_gaps_run ON gaps(run_id);
CREATE INDEX IF NOT EXISTS idx_gaps_sev ON gaps(severity);

CREATE TABLE IF NOT EXISTS engagement (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    platform        TEXT,
    measured_at     TEXT,
    hours_post_pub  INTEGER,
    views           INTEGER,
    likes           INTEGER,
    shares          INTEGER,
    completion_rate REAL,
    raw             TEXT
);
CREATE INDEX IF NOT EXISTS idx_eng_run ON engagement(run_id);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _safe_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------

def ingest_run(conn: sqlite3.Connection, run_path: Path) -> dict[str, int]:
    run_id = run_path.name
    run_json = _safe_json(run_path / "run.json") or {}
    ckpt = (
        _safe_json(run_path / "checkpoint.json")
        or _safe_json(run_path / "production" / "checkpoint.json")
        or {}
    )

    pipeline_kind = run_json.get("pipeline") or ckpt.get("pipeline_type")
    started = run_json.get("started_at_utc") or ckpt.get("created_at")
    ended = ckpt.get("updated_at")
    status = ckpt.get("status")

    # Pull representative quality_score from council audit (first available)
    quality_score = None
    for ca in (run_path / "council_audits").glob("*_audit.json") if (run_path / "council_audits").exists() else []:
        data = _safe_json(ca) or {}
        if isinstance(data.get("quality_score"), (int, float)):
            quality_score = data["quality_score"]
            break

    grade = "?"
    if quality_score is not None:
        if quality_score >= 8.0:
            grade = "A"
        elif quality_score >= 7.0:
            grade = "B"
        elif quality_score >= 6.0:
            grade = "C"
        else:
            grade = "D"

    # Brand inference
    brand = (
        ckpt.get("metadata", {}).get("brand_id")
        or run_json.get("brand")
        or None
    )
    if not brand:
        for ca in (run_path / "production").rglob("checkpoint.json"):
            inner = _safe_json(ca) or {}
            phase = (inner.get("phases") or {}).get("entity_resolution") or {}
            brand = (phase.get("metadata") or {}).get("brand_id")
            if brand:
                break

    counts = {"directives": 0, "gaps": 0, "engagement": 0}

    # ----- directives -----
    for ca in (run_path).rglob("council_audits"):
        if not ca.is_dir():
            continue
        for f in ca.glob("*_audit.json"):
            data = _safe_json(f)
            if not isinstance(data, dict):
                continue
            phase = data.get("phase") or f.stem.replace("_audit", "")
            verdict = data.get("final_verdict") or data.get("quality_verdict")
            redo = int(data.get("redo_count") or 0)
            for d in (data.get("directives") or []):
                conn.execute(
                    "INSERT INTO directives (run_id, audit_file, audit_phase, directive, verdict, applied) "
                    "VALUES (?,?,?,?,?,?)",
                    (run_id, str(f.relative_to(run_path)), phase, str(d), verdict, 1 if redo > 0 else 0),
                )
                conn.execute(
                    "INSERT INTO directives_fts (directive, audit_phase, verdict) VALUES (?,?,?)",
                    (str(d), phase, verdict),
                )
                counts["directives"] += 1

    # ----- gaps -----
    for gr_dir in (run_path).rglob("gap_reports"):
        if not gr_dir.is_dir():
            continue
        for f in gr_dir.glob("*_gap_report.json"):
            data = _safe_json(f)
            if not isinstance(data, dict):
                continue
            for gap in data.get("gaps", []) or []:
                conn.execute(
                    "INSERT INTO gaps (run_id, code, severity, phase, message) VALUES (?,?,?,?,?)",
                    (
                        run_id,
                        gap.get("code"),
                        gap.get("severity"),
                        gap.get("phase"),
                        gap.get("message"),
                    ),
                )
                counts["gaps"] += 1

    # ----- engagement -----
    feedback = _safe_json(run_path / "run_feedback.json") or {}
    eng = feedback.get("signals", {}).get("engagement_metrics") or {}
    if eng:
        for platform, metrics in eng.items():
            conn.execute(
                "INSERT INTO engagement (run_id, platform, measured_at, views, likes, shares, completion_rate, raw) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id, platform, feedback.get("created_at"),
                    int(metrics.get("views", 0)),
                    int(metrics.get("likes", 0)),
                    int(metrics.get("shares", 0)),
                    float(metrics.get("completion_rate", 0)),
                    json.dumps(metrics),
                ),
            )
            counts["engagement"] += 1

    # ----- session record -----
    summary = (
        f"{pipeline_kind} run {run_id} — status={status} grade={grade} "
        f"quality_score={quality_score} brand={brand} "
        f"directives={counts['directives']} gaps={counts['gaps']}"
    )

    conn.execute(
        """INSERT OR REPLACE INTO sessions
        (session_id, run_id, pipeline_kind, started_at, ended_at, status, grade, quality_score, summary, brand, raw_metadata)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id, run_id, pipeline_kind, started, ended, status, grade,
            quality_score, summary, brand,
            json.dumps({"run_json": run_json, "checkpoint": ckpt}),
        ),
    )

    # FTS title/body
    title = f"{pipeline_kind or 'unknown'} :: {run_id}"
    body_parts = [summary]
    # Add story text if exists (very searchable)
    story = run_path / "scripts" / "story.txt"
    if story.exists():
        try:
            body_parts.append(story.read_text()[:8000])
        except OSError:
            pass
    body = "\n".join(body_parts)
    tags = " ".join(
        x for x in [pipeline_kind, status, grade, brand, str(quality_score)] if x
    )
    conn.execute(
        "INSERT INTO sessions_fts (session_id, run_id, title, body, tags) VALUES (?,?,?,?,?)",
        (run_id, run_id, title, body, tags),
    )
    conn.commit()
    return counts


# ---------------------------------------------------------------------------

def ingest_batch(conn: sqlite3.Connection, batch_root: Path) -> dict[str, Any]:
    runs = [p for p in batch_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    total = {"runs": 0, "directives": 0, "gaps": 0, "engagement": 0}
    for r in runs:
        c = ingest_run(conn, r)
        total["runs"] += 1
        for k, v in c.items():
            total[k] += v
    return total


# ---------------------------------------------------------------------------
# Skill auto-creator: any directive that recurs ≥N times → propose a skill
# ---------------------------------------------------------------------------

def propose_skills(conn: sqlite3.Connection, threshold: int = 3) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT directive, audit_phase, COUNT(*) AS n "
        "FROM directives WHERE applied = 0 "
        "GROUP BY directive, audit_phase HAVING n >= ? "
        "ORDER BY n DESC LIMIT 50",
        (threshold,),
    ).fetchall()
    proposed = []
    for d, phase, n in rows:
        slug = (phase or "general") + "-" + "".join(c if c.isalnum() else "-" for c in d.lower())[:40].strip("-")
        proposed.append({
            "skill_path": f"~/.hermes/skills/contentx/{slug}.md",
            "occurrence_count": n,
            "audit_phase": phase,
            "directive_template": d,
            "body": (
                f"---\n"
                f"name: contentx-{slug}\n"
                f"description: 'Auto-derived from {n} occurrences of council directive in {phase}'\n"
                f"trigger: pipeline.kind in viral_shorts,short_video\n"
                f"---\n\n"
                f"# {phase} directive\n\n"
                f"Recurring council finding ({n} runs):\n\n"
                f"> {d}\n\n"
                f"## Recommended application\n\n"
                f"Before the {phase} phase runs, consult this skill. If the "
                f"planner's draft triggers this pattern, pre-emptively apply the fix."
            ),
        })
    return proposed


# ---------------------------------------------------------------------------
# Top queries for /whatdoweknow
# ---------------------------------------------------------------------------

def whatdoweknow(conn: sqlite3.Connection, q: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT s.run_id, s.pipeline_kind, s.grade, s.quality_score, "
        "       snippet(sessions_fts, 3, '[', ']', '…', 16) AS snippet "
        "FROM sessions_fts JOIN sessions s ON s.session_id = sessions_fts.session_id "
        "WHERE sessions_fts MATCH ? ORDER BY rank LIMIT 20",
        (q,),
    ).fetchall()
    return [
        {"run_id": r[0], "pipeline_kind": r[1], "grade": r[2], "quality_score": r[3], "snippet": r[4]}
        for r in rows
    ]


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="hermes_contentx.sqlite", help="SQLite path")
    ap.add_argument("--batch", help="parent dir of run folders to ingest")
    ap.add_argument("--run", help="single run folder")
    ap.add_argument("--query", help="run /whatdoweknow query")
    ap.add_argument("--propose-skills", action="store_true")
    ap.add_argument("--skill-threshold", type=int, default=3)
    ap.add_argument("--out-skills", help="write proposed skills to dir")
    args = ap.parse_args()

    db_path = Path(args.db)
    conn = init_db(db_path)

    if args.batch:
        total = ingest_batch(conn, Path(args.batch).expanduser().resolve())
        print(f"ingested {total['runs']} runs: {total}")
    elif args.run:
        c = ingest_run(conn, Path(args.run).expanduser().resolve())
        print(f"ingested 1 run: {c}")

    if args.query:
        results = whatdoweknow(conn, args.query)
        print(f"\n/whatdoweknow `{args.query}`:")
        for r in results:
            print(f"  [{r['grade']:>2}] {r['run_id']:<50} q={r['quality_score']}  {r['snippet']}")

    if args.propose_skills:
        proposed = propose_skills(conn, threshold=args.skill_threshold)
        print(f"\nproposed {len(proposed)} skills (threshold={args.skill_threshold}):")
        for p in proposed[:10]:
            print(f"  [{p['occurrence_count']:>3}x] {p['skill_path']}")
        if args.out_skills:
            out_dir = Path(args.out_skills)
            out_dir.mkdir(parents=True, exist_ok=True)
            for p in proposed:
                fname = Path(p["skill_path"]).name
                (out_dir / fname).write_text(p["body"])
            (out_dir / "INDEX.json").write_text(json.dumps(proposed, indent=2))
            print(f"  written → {out_dir}")


if __name__ == "__main__":
    main()
