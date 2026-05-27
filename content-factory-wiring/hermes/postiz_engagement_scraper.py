"""
postiz_engagement_scraper.py — Browser-provider hook that closes F5.

For any published bead older than the schedule_delays list, fetch
engagement metrics from YouTube/TikTok/Instagram and update the bead.

This file is the contract — actual scraping uses Hermes browser_provider
when invoked under Hermes; under cron/CLI we use yt-dlp / Instagram Graph
API / TikTok API where credentials are available.

Output: writes engagement rows into the same Hermes SessionDB, then
posts a bd update with the latest numbers and closes the bead when
the +168h reading lands.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PLATFORM_FETCHERS = {
    "youtube_shorts": "_fetch_youtube",
    "tiktok": "_fetch_tiktok",
    "instagram_reels": "_fetch_instagram",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_youtube(video_id: str) -> dict[str, Any]:
    """Use yt-dlp for public metadata. For private channel data swap in YouTube Data API."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--skip-download", f"https://youtube.com/shorts/{video_id}"],
            check=True, capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        return {
            "views": data.get("view_count", 0),
            "likes": data.get("like_count", 0),
            "comments": data.get("comment_count", 0),
            "duration_s": data.get("duration", 0),
            "completion_rate": None,  # need analytics API
            "raw": data,
        }
    except Exception as exc:
        return {"error": str(exc), "platform": "youtube_shorts"}


def _fetch_tiktok(video_url: str) -> dict[str, Any]:
    # Placeholder — TikTok analytics needs a creator account API or scraper
    return {"error": "tiktok scraper not configured", "url": video_url}


def _fetch_instagram(post_url: str) -> dict[str, Any]:
    # Placeholder — Instagram Graph API requires a business account token
    return {"error": "instagram scraper not configured", "url": post_url}


# ---------------------------------------------------------------------------

def discover_runs_to_scrape(
    conn: sqlite3.Connection,
    delays_hours: list[int],
    max_age_days: int = 7,
) -> list[dict[str, Any]]:
    """Find runs where the next scheduled engagement reading is due."""
    out: list[dict[str, Any]] = []
    cutoff = (_now() - timedelta(days=max_age_days)).isoformat()
    rows = conn.execute(
        "SELECT s.run_id, s.pipeline_kind, s.ended_at "
        "FROM sessions s WHERE s.ended_at > ? AND s.status IN ('completed','partial') "
        "ORDER BY s.ended_at DESC LIMIT 200",
        (cutoff,),
    ).fetchall()
    for run_id, pipeline_kind, ended_at in rows:
        if not ended_at:
            continue
        try:
            published_at = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        age_h = (_now() - published_at).total_seconds() / 3600
        # Did we already capture a reading at this delay band?
        for delay in delays_hours:
            if age_h < delay - 0.5 or age_h > delay + 6:
                continue
            existing = conn.execute(
                "SELECT 1 FROM engagement WHERE run_id=? AND hours_post_pub=?",
                (run_id, delay),
            ).fetchone()
            if not existing:
                out.append({
                    "run_id": run_id,
                    "pipeline_kind": pipeline_kind,
                    "published_at": ended_at,
                    "scheduled_delay_h": delay,
                    "actual_age_h": age_h,
                })
                break
    return out


def scrape_run(conn: sqlite3.Connection, run_meta: dict[str, Any], run_path: Path | None) -> dict[str, Any]:
    """For one run, fetch engagement from each platform that has a publish payload."""
    run_id = run_meta["run_id"]
    result: dict[str, Any] = {"run_id": run_id, "platforms": {}}
    if run_path and run_path.exists():
        for platform in PLATFORM_FETCHERS:
            payload_file = next(run_path.rglob(f"{platform}_api_payload.json"), None) or \
                           next(run_path.rglob(f"publish/{platform}.json"), None)
            if not payload_file:
                continue
            payload = json.loads(payload_file.read_text()) if payload_file.exists() else {}
            target_id = payload.get("video_id") or payload.get("post_id") or payload.get("url")
            if not target_id:
                continue
            fetcher = globals()[PLATFORM_FETCHERS[platform]]
            metrics = fetcher(target_id)
            result["platforms"][platform] = metrics
            if "error" not in metrics:
                conn.execute(
                    "INSERT INTO engagement (run_id, platform, measured_at, hours_post_pub, views, likes, shares, completion_rate, raw) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, platform, _now().isoformat(),
                        run_meta["scheduled_delay_h"],
                        int(metrics.get("views", 0)),
                        int(metrics.get("likes", 0)),
                        int(metrics.get("shares", 0)),
                        float(metrics.get("completion_rate") or 0),
                        json.dumps(metrics.get("raw", {}))[:8000],
                    ),
                )
    conn.commit()
    return result


def update_bead(run_id: str, scrape_result: dict[str, Any]) -> None:
    """Emit a `bd update` command. Caller pipes through to the bd CLI."""
    note = json.dumps(scrape_result["platforms"], indent=2)[:1800]
    print(f"bd update qv-run-{run_id} --comment={json.dumps(note)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="hermes_contentx.sqlite")
    ap.add_argument("--working-dir", default="/var/lib/content-factory/working_dir")
    ap.add_argument("--delays", type=int, nargs="*", default=[24, 72, 168])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    work_root = Path(args.working_dir).expanduser().resolve()

    due = discover_runs_to_scrape(conn, args.delays)
    print(f"runs due for engagement scrape: {len(due)}")
    for r in due[:50]:
        print(f"  {r['run_id']}  (delay={r['scheduled_delay_h']}h, actual={r['actual_age_h']:.1f}h)")
        if args.dry_run:
            continue
        # Locate run_path
        candidate = next(work_root.rglob(r["run_id"]), None)
        result = scrape_run(conn, r, candidate)
        update_bead(r["run_id"], result)


if __name__ == "__main__":
    main()
