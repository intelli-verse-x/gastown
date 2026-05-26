"""G14 Chain of Custody — append-only HMAC-signed event log + Merkle root + retention.

Every gate result, approval, asset hash, and pipeline transition is appended
to {run_path}/chain_of_custody.jsonl as a single line:
    {seq, prev_hash, event, hmac}

Each entry's hmac covers (seq, prev_hash, canonical_event). Tampering breaks
the chain because seq+1's prev_hash references seq's hash; recomputing any
prior line invalidates every line after it.

A daily Merkle root is written to chain_of_custody_root.json.

Retention: retention.json declares the legally-required retention period
(default 7 years). G14 fails if the run is past its retention without an
archived snapshot.

CLI:
    python g14_chain_of_custody.py verify <run_path>          # verify chain integrity
    python g14_chain_of_custody.py append <run_path> --event '{"kind":"gate","gate":"G6"}'
    python g14_chain_of_custody.py merkle <run_path>          # compute root for today's entries
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from . import GateFinding, GateResult, now_utc, sign, verify, _signing_key
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign, verify, _signing_key  # type: ignore


import hmac

DEFAULT_RETENTION_YEARS = 7


def _entry_hash(entry: dict[str, Any]) -> str:
    safe = {k: v for k, v in entry.items() if k != "hmac"}
    canonical = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _hmac_entry(entry: dict[str, Any]) -> str:
    safe = {k: v for k, v in entry.items() if k != "hmac"}
    canonical = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_signing_key(), canonical, hashlib.sha256).hexdigest()


def append(run_path: Path, event: dict[str, Any]) -> dict[str, Any]:
    log_path = run_path / "chain_of_custody.jsonl"
    seq = 0
    prev_hash = "GENESIS"
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            if not line.strip(): continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
            seq = max(seq, last.get("seq", -1) + 1)
            prev_hash = _entry_hash(last)
    entry = {
        "seq": seq,
        "prev_hash": prev_hash,
        "at": now_utc(),
        "event": event,
    }
    entry["hmac"] = _hmac_entry(entry)
    with log_path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def verify_chain(run_path: Path) -> tuple[bool, list[GateFinding]]:
    findings: list[GateFinding] = []
    log_path = run_path / "chain_of_custody.jsonl"
    if not log_path.exists():
        findings.append(GateFinding(
            code="G14_no_log",
            severity="blocker",
            message="chain_of_custody.jsonl missing — no audit trail exists",
        ))
        return False, findings
    expected_prev = "GENESIS"
    last_seq = -1
    for i, line in enumerate(log_path.read_text().splitlines()):
        if not line.strip(): continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(GateFinding(
                code="G14_log_malformed",
                severity="blocker",
                message=f"line {i+1}: invalid JSON ({exc})",
            ))
            continue
        if entry.get("prev_hash") != expected_prev:
            findings.append(GateFinding(
                code="G14_chain_broken",
                severity="blocker",
                message=(
                    f"line {i+1} (seq={entry.get('seq')}): prev_hash mismatch — "
                    f"chain tampered or out of order"
                ),
                measurement={"expected": expected_prev[:16], "got": entry.get("prev_hash", "")[:16]},
            ))
        if entry.get("seq") != last_seq + 1:
            findings.append(GateFinding(
                code="G14_seq_gap",
                severity="blocker",
                message=f"line {i+1}: seq {entry.get('seq')} != expected {last_seq+1}",
            ))
        if not hmac.compare_digest(_hmac_entry(entry), entry.get("hmac", "")):
            findings.append(GateFinding(
                code="G14_hmac_invalid",
                severity="blocker",
                message=f"line {i+1} (seq={entry.get('seq')}): HMAC verification failed",
            ))
        last_seq = entry.get("seq", last_seq)
        expected_prev = _entry_hash(entry)
    return not findings, findings


def merkle_root(run_path: Path, day: str | None = None) -> dict[str, Any]:
    log_path = run_path / "chain_of_custody.jsonl"
    if not log_path.exists():
        return {"error": "no log"}
    day_str = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    leaves: list[str] = []
    for line in log_path.read_text().splitlines():
        if not line.strip(): continue
        try: entry = json.loads(line)
        except json.JSONDecodeError: continue
        if (entry.get("at") or "")[:10] == day_str:
            leaves.append(_entry_hash(entry))
    if not leaves:
        return {"day": day_str, "leaves": 0, "root": None}
    layer = leaves[:]
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer), 2):
            a = layer[i]
            b = layer[i + 1] if i + 1 < len(layer) else layer[i]
            nxt.append(hashlib.sha256((a + b).encode()).hexdigest())
        layer = nxt
    root = layer[0]
    out_path = run_path / "chain_of_custody_root.json"
    existing = json.loads(out_path.read_text()) if out_path.exists() else {"roots": {}}
    existing["roots"][day_str] = {"root": root, "leaves": len(leaves)}
    out_path.write_text(json.dumps(existing, indent=2))
    return {"day": day_str, "leaves": len(leaves), "root": root}


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    log_path = run_path / "chain_of_custody.jsonl"
    if not log_path.exists():
        findings.append(GateFinding(
            code="G14_no_log",
            severity="blocker",
            message="chain_of_custody.jsonl missing — no audit trail exists",
        ))
        return _result(findings, run_path, tier, passed=False)

    ok, chain_findings = verify_chain(run_path)
    findings.extend(chain_findings)

    # Retention check
    retention_file = run_path / "retention.json"
    if retention_file.exists():
        try:
            ret = json.loads(retention_file.read_text())
            yrs = float(ret.get("years", DEFAULT_RETENTION_YEARS))
            created = ret.get("created_at") or ""
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    expiry = created_dt + timedelta(days=int(yrs * 365.25))
                    if datetime.now(timezone.utc) > expiry and not ret.get("archived_at"):
                        findings.append(GateFinding(
                            code="G14_retention_expired_no_archive",
                            severity="blocker",
                            message=f"retention expired {expiry.isoformat()} without an archive record",
                        ))
                except ValueError:
                    findings.append(GateFinding(
                        code="G14_retention_invalid",
                        severity="critical",
                        message=f"retention.created_at unparseable: {created}",
                    ))
        except json.JSONDecodeError:
            findings.append(GateFinding(
                code="G14_retention_malformed",
                severity="critical",
                message="retention.json invalid JSON",
            ))
    else:
        findings.append(GateFinding(
            code="G14_no_retention_policy",
            severity="medium" if tier in ("internal", "indie") else "critical",
            message=f"retention.json missing — default {DEFAULT_RETENTION_YEARS}y policy assumed",
        ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G14", gate_name="chain_of_custody", passed=passed, tier=tier,
        findings=findings, run_id=run_path.name, evaluated_at=now_utc(),
    )
    r.signature = sign(r.to_dict())
    return r


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "verify":
        argv = argv[1:]
    if argv and argv[0] in ("append", "merkle"):
        cmd = argv[0]
        sp = argparse.ArgumentParser()
        sp.add_argument("run_path")
        if cmd == "append":
            sp.add_argument("--event", required=True)
        else:
            sp.add_argument("--day")
        a = sp.parse_args(argv[1:])
        if cmd == "append":
            entry = append(Path(a.run_path).resolve(), json.loads(a.event))
            print(json.dumps(entry, indent=2))
        else:
            print(json.dumps(merkle_root(Path(a.run_path).resolve(), a.day), indent=2))
        return 0

    ap = argparse.ArgumentParser()
    ap.add_argument("run_path")
    ap.add_argument("--tier", default="aa")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = evaluate(Path(args.run_path).expanduser().resolve(), args.tier)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
    else:
        print(f"[G14 chain_of_custody] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
