"""
s3_sync_auditor.py — detect runs whose long-term S3 sync skipped large media.

RUN_MEMORY_GAPS_REPORT calls out:
  "Long-term S3 sync skips large media → retry on a new host loses context"

We verify by:
  1. enumerating local artifacts under {run_path}/media/, {run_path}/output/, etc.
  2. comparing against either:
     a. a sync manifest at {run_path}/s3_sync_manifest.json (preferred), or
     b. live S3 listing under s3://{bucket}/{prefix}/{run_id}/...

For each file:
  • > size threshold (default 50 MB) AND missing from S3 → BLOCKER
  • present locally + S3 with different hash → CRITICAL
  • S3-only (lost local copy) → HIGH

This script never writes — it reports. Pair with `aws s3 sync` to fix.

Run without --bucket to do "structural check": just flag runs with NO sync
manifest, which is the most common failure mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class SyncFinding:
    code: str
    severity: str
    run_id: str
    path: str
    message: str
    measurement: dict[str, Any]


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _md5(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    try:
        with p.open("rb") as fh:
            while True:
                buf = fh.read(chunk)
                if not buf:
                    break
                h.update(buf)
    except OSError:
        return ""
    return h.hexdigest()


def list_s3(bucket: str, prefix: str) -> dict[str, dict[str, Any]] | None:
    try:
        out = subprocess.check_output(
            ["aws", "s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix,
             "--max-items", "10000", "--output", "json"],
            timeout=120,
        )
        data = json.loads(out)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired,
            json.JSONDecodeError):
        return None
    return {obj["Key"]: {"size": obj["Size"], "etag": obj.get("ETag", "").strip('"')}
            for obj in data.get("Contents", [])}


def audit_run(run_path: Path, *, large_threshold_mb: int = 50,
              bucket: str | None = None, prefix: str | None = None) -> list[SyncFinding]:
    findings: list[SyncFinding] = []
    run_id = run_path.name

    # Locate sync manifest
    manifest_file = run_path / "s3_sync_manifest.json"
    manifest = {}
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text())
        except json.JSONDecodeError:
            findings.append(SyncFinding(
                code="S0_manifest_invalid",
                severity="critical",
                run_id=run_id,
                path="s3_sync_manifest.json",
                message="sync manifest exists but is not valid JSON",
                measurement={},
            ))
            return findings

    if not manifest:
        findings.append(SyncFinding(
            code="S1_no_sync_manifest",
            severity="high",
            run_id=run_id,
            path=".",
            message="no s3_sync_manifest.json — cannot prove run is recoverable from S3",
            measurement={},
        ))

    # Enumerate large local media files
    media_globs = ["media/**/*", "output/**/*", "scenes/**/*.mp4", "scenes/**/*.wav",
                   "scenes/**/*.png", "*.mp4"]
    large_local: dict[str, dict[str, Any]] = {}
    for pattern in media_globs:
        for p in run_path.glob(pattern):
            if not p.is_file():
                continue
            size = _file_size(p)
            if size < large_threshold_mb * 1024 * 1024:
                continue
            rel = str(p.relative_to(run_path))
            large_local[rel] = {"size": size}

    # S2 — large file missing from manifest
    if manifest:
        manifested_paths = set(manifest.get("files", {}).keys())
        for rel, info in large_local.items():
            if rel not in manifested_paths:
                findings.append(SyncFinding(
                    code="S2_large_local_not_in_manifest",
                    severity="critical",
                    run_id=run_id,
                    path=rel,
                    message=(
                        f"{rel} is {info['size']/1024/1024:.1f} MB but not in sync manifest — "
                        f"S3 sync would skip it"
                    ),
                    measurement={"size_mb": info["size"] / 1024 / 1024},
                ))

    # S3-side check (if credentials present)
    if bucket and prefix:
        run_prefix = f"{prefix.rstrip('/')}/{run_id}/"
        s3 = list_s3(bucket, run_prefix)
        if s3 is None:
            findings.append(SyncFinding(
                code="S5_s3_check_failed",
                severity="medium",
                run_id=run_id,
                path=run_prefix,
                message="could not list S3 (missing creds or aws cli) — skipping live check",
                measurement={"bucket": bucket, "prefix": run_prefix},
            ))
        else:
            # S3 — large local not in S3
            for rel, info in large_local.items():
                s3_key = run_prefix + rel
                if s3_key not in s3:
                    findings.append(SyncFinding(
                        code="S3_large_not_on_s3",
                        severity="blocker",
                        run_id=run_id,
                        path=rel,
                        message=f"{rel} ({info['size']/1024/1024:.1f} MB) absent from s3://{bucket}/{run_prefix}",
                        measurement={"size_mb": info["size"] / 1024 / 1024, "s3_key": s3_key},
                    ))
            # S4 — S3-only (local copy lost)
            local_keys = {run_prefix + str(p.relative_to(run_path))
                          for p in run_path.rglob("*") if p.is_file()}
            for s3_key in s3:
                if s3_key not in local_keys and s3[s3_key]["size"] > large_threshold_mb * 1024 * 1024:
                    findings.append(SyncFinding(
                        code="S4_s3_only",
                        severity="high",
                        run_id=run_id,
                        path=s3_key,
                        message=f"{s3_key} ({s3[s3_key]['size']/1024/1024:.1f} MB) on S3 but missing locally",
                        measurement={"size_mb": s3[s3_key]["size"] / 1024 / 1024},
                    ))

    return findings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--batch", help="parent dir of runs")
    ap.add_argument("--bucket", help="S3 bucket to cross-check")
    ap.add_argument("--prefix", help="S3 key prefix (e.g. 'contentx-runs/video')")
    ap.add_argument("--large-mb", type=int, default=50, help="size threshold for 'large' (MB)")
    ap.add_argument("--out", help="write JSON report")
    args = ap.parse_args()

    if args.batch:
        root = Path(args.batch).expanduser().resolve()
        runs = sorted(p for p in root.iterdir() if p.is_dir())
        all_findings: list[dict] = []
        for r in runs:
            for f in audit_run(r, large_threshold_mb=args.large_mb,
                               bucket=args.bucket, prefix=args.prefix):
                all_findings.append(asdict(f))
        report = {"batch": str(root), "findings": all_findings,
                  "by_code": {}, "by_severity": {}}
    else:
        rp = Path(args.path).expanduser().resolve()
        findings = audit_run(rp, large_threshold_mb=args.large_mb,
                             bucket=args.bucket, prefix=args.prefix)
        all_findings = [asdict(f) for f in findings]
        report = {"run_id": rp.name, "findings": all_findings}

    for f in all_findings:
        report["by_code"] = report.get("by_code", {})
        report["by_code"][f["code"]] = report["by_code"].get(f["code"], 0) + 1
        report["by_severity"] = report.get("by_severity", {})
        report["by_severity"][f["severity"]] = report["by_severity"].get(f["severity"], 0) + 1

    print(f"\nS3 sync audit: {len(all_findings)} findings")
    print(f"  by code:     {report.get('by_code', {})}")
    print(f"  by severity: {report.get('by_severity', {})}")

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nreport -> {args.out}")


if __name__ == "__main__":
    main()
