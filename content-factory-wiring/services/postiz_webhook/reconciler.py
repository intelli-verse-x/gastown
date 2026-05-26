"""Postiz webhook reconciler.

Sweeps `liveops/orphan/*.json` files (engagement events that arrived before
publish_metadata.json was written for that run) and re-attempts mapping.

Runs every 30 min via cron.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

log = logging.getLogger("postiz-reconciler")
logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "postiz_webhook"))

from server import _find_run_path, _update_bead  # type: ignore  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--working-dir", required=True)
    ap.add_argument("--orphan-dir", default="/var/lib/contentx/orphan_engagement")
    ap.add_argument("--max-age-hours", type=int, default=48)
    args = ap.parse_args()

    orphan = Path(args.orphan_dir)
    if not orphan.exists():
        log.info("no orphan dir; nothing to reconcile")
        return 0

    cutoff = time.time() - args.max_age_hours * 3600
    reconciled = 0
    aged_out = 0

    for f in orphan.glob("*.json"):
        try:
            stat = f.stat()
            if stat.st_mtime < cutoff:
                f.rename(f.with_suffix(".json.expired"))
                aged_out += 1
                continue
            payload = json.loads(f.read_text())
            post_id = payload.get("post_id") or ""
            run_id_hint = payload.get("run_id") or payload.get("contentx_run_id")
            run_path = _find_run_path(post_id, run_id_hint)
            if not run_path:
                continue
            created, bead_id = _update_bead(run_path, post_id, payload)
            log.info(f"reconciled {post_id} -> {run_path.name} (bead {bead_id})")
            reconciled += 1
            f.unlink()
        except Exception as exc:
            log.warning(f"reconcile failed for {f}: {exc}")

    log.info(f"reconciled={reconciled} aged_out={aged_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
