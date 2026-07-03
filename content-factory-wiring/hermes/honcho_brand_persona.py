"""
honcho_brand_persona.py — bootstrap a Honcho persona per brand from past runs.

Hermes' Honcho subsystem does dialectic user modeling. We give it a persona per
brand seeded with everything the brand's prior runs have told us:

  • brand_colors.json palettes
  • voice_registry.json voice assignments
  • banned/preferred terms from compliance audits
  • council_audits scores by run for that brand (which directives recurred)
  • engagement metrics by platform

Output: One persona JSON per brand at ~/.hermes/personas/contentx/<brand>.json.
The Hermes orchestrator then loads it via `honcho.load("contentx/<brand>")`
before every script-planning phase.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


def gather_brand_runs(conn: sqlite3.Connection) -> dict[str, list[str]]:
    rows = conn.execute(
        "SELECT brand, run_id FROM sessions WHERE brand IS NOT NULL AND brand != ''"
    ).fetchall()
    brands: dict[str, list[str]] = {}
    for brand, run_id in rows:
        brands.setdefault(brand, []).append(run_id)
    return brands


def build_persona(brand: str, run_ids: list[str], working_dir: Path, conn: sqlite3.Connection) -> dict[str, Any]:
    palettes_seen: Counter[str] = Counter()
    voices_seen: Counter[str] = Counter()
    recurring_directives: list[tuple[str, str, int]] = conn.execute(
        "SELECT directive, audit_phase, COUNT(*) FROM directives d "
        "WHERE d.run_id IN (" + ",".join("?" * len(run_ids)) + ") "
        "GROUP BY directive ORDER BY COUNT(*) DESC LIMIT 20",
        run_ids,
    ).fetchall()

    engagement_avg = conn.execute(
        "SELECT platform, AVG(views), AVG(likes), AVG(completion_rate) FROM engagement "
        "WHERE run_id IN (" + ",".join("?" * len(run_ids)) + ") "
        "GROUP BY platform",
        run_ids,
    ).fetchall()

    for run_id in run_ids:
        run_dir = next(working_dir.rglob(run_id), None)
        if not run_dir:
            continue
        for bc in run_dir.rglob("brand_colors.json"):
            try:
                bc_data = json.loads(bc.read_text())
                for color in bc_data.values() if isinstance(bc_data, dict) else []:
                    if isinstance(color, str) and color.startswith("#"):
                        palettes_seen[color] += 1
            except Exception:
                continue
        for vr in run_dir.rglob("voice_registry.json"):
            try:
                vr_data = json.loads(vr.read_text())
                for voice in (vr_data or {}).values() if isinstance(vr_data, dict) else []:
                    if isinstance(voice, str):
                        voices_seen[voice] += 1
            except Exception:
                continue

    top_palettes = [c for c, _ in palettes_seen.most_common(8)]
    top_voices = [v for v, _ in voices_seen.most_common(4)]

    persona = {
        "version": 1,
        "brand": brand,
        "run_count": len(run_ids),
        "preferred_palette": top_palettes,
        "preferred_voices": top_voices,
        "recurring_directives": [
            {"directive": d, "phase": p, "occurrence": n}
            for d, p, n in recurring_directives
        ],
        "engagement_baseline": {
            row[0]: {"avg_views": row[1], "avg_likes": row[2], "avg_completion": row[3]}
            for row in engagement_avg
        },
        "honcho_dialectic_hints": [
            f"Brand '{brand}' rejected these patterns in past runs (council directives, "
            f"occurrence count in parentheses):",
            *[f"  - ({n}x) {d[:120]}" for d, _, n in recurring_directives[:8]],
        ],
        "applies_to_phases": ["ideation", "script", "director_brief", "brand_audit", "publish"],
    }
    return persona


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--working-dir", required=True)
    ap.add_argument("--out-dir", default="hermes/personas")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    brands = gather_brand_runs(conn)
    print(f"discovered {len(brands)} brands across {sum(len(r) for r in brands.values())} runs")
    written = 0
    for brand, runs in brands.items():
        persona = build_persona(brand, runs, Path(args.working_dir), conn)
        path = out_dir / f"{brand}.json"
        path.write_text(json.dumps(persona, indent=2))
        written += 1
        print(f"  {brand:<24} runs={persona['run_count']:>3}  palette={len(persona['preferred_palette'])} voices={len(persona['preferred_voices'])} → {path}")

    print(f"\nwrote {written} personas to {out_dir}")


if __name__ == "__main__":
    main()
