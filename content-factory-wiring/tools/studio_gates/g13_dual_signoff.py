"""G13 Dual Sign-off — Creative Director + Technical Director HMAC signatures.

Both signatures required for tier ≥ aa. Signatures cover:
    (run_id, output_hash, gate_results_hash, signed_at, signer)
HMAC-SHA256 with CONTENTX_CERT_KEY.

Usage:
    python g13_dual_signoff.py <run_path> --tier aa                 # verify
    python g13_dual_signoff.py sign --run <run_path> \
            --role creative_director --signer "Alice Chen"          # produce signature
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import GateFinding, GateResult, now_utc, sign, verify
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign, verify  # type: ignore


REQUIRED_ROLES = ("creative_director", "technical_director")


def _output_hash(run_path: Path) -> str:
    """Hash of every final output mp4 + caption + thumb."""
    h = hashlib.sha256()
    for pattern in ("final_video*.mp4", "*.srt", "*.vtt", "*thumbnail*"):
        for f in sorted(run_path.rglob(pattern)):
            if f.is_file():
                h.update(f.relative_to(run_path).as_posix().encode())
                h.update(str(f.stat().st_size).encode())
    return h.hexdigest()


def _gate_results_hash(run_path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(run_path.rglob("gates/*.json")):
        if f.is_file():
            try:
                h.update(json.dumps(json.loads(f.read_text()), sort_keys=True).encode())
            except Exception:
                continue
    return h.hexdigest()


def make_signature_payload(run_path: Path, role: str, signer: str, signed_at: str | None = None) -> dict[str, Any]:
    return {
        "run_id": run_path.name,
        "role": role,
        "signer": signer,
        "signed_at": signed_at or now_utc(),
        "output_hash": _output_hash(run_path),
        "gate_results_hash": _gate_results_hash(run_path),
    }


def sign_for(run_path: Path, role: str, signer: str) -> dict[str, Any]:
    payload = make_signature_payload(run_path, role, signer)
    payload["signature"] = sign(payload)
    approvals_dir = run_path / "approvals"
    approvals_dir.mkdir(exist_ok=True)
    out = approvals_dir / f"{role}.json"
    out.write_text(json.dumps(payload, indent=2))
    return payload


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    if tier in ("internal", "indie"):
        # Dual sign-off not required at low tiers
        return _result(findings, run_path, tier, passed=True)

    approvals_dir = run_path / "approvals"
    if not approvals_dir.exists():
        findings.append(GateFinding(
            code="G13_no_approvals_dir",
            severity="blocker",
            message="approvals/ directory missing — no signatures recorded",
        ))
        return _result(findings, run_path, tier, passed=False)

    for role in REQUIRED_ROLES:
        sig_file = approvals_dir / f"{role}.json"
        if not sig_file.exists():
            findings.append(GateFinding(
                code="G13_missing_signature",
                severity="blocker",
                message=f"approvals/{role}.json absent",
                measurement={"role": role},
            ))
            continue
        try:
            payload = json.loads(sig_file.read_text())
        except json.JSONDecodeError as exc:
            findings.append(GateFinding(
                code="G13_signature_invalid_json",
                severity="blocker",
                message=f"approvals/{role}.json invalid: {exc}",
            ))
            continue

        if not verify(payload):
            findings.append(GateFinding(
                code="G13_signature_invalid",
                severity="blocker",
                message=f"approvals/{role}.json HMAC verification failed — possible tampering or key mismatch",
                measurement={"role": role},
            ))
            continue

        # Re-derive hashes and confirm signed-over values match current state
        current_output_hash = _output_hash(run_path)
        if payload.get("output_hash") != current_output_hash:
            findings.append(GateFinding(
                code="G13_output_changed_post_signoff",
                severity="blocker",
                message=(
                    f"approvals/{role}.json: output_hash signed over does not match current output "
                    f"(content changed after sign-off; re-approval required)"
                ),
                measurement={
                    "role": role,
                    "signed_output_hash": payload.get("output_hash", "")[:16],
                    "current_output_hash": current_output_hash[:16],
                },
            ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G13", gate_name="dual_signoff", passed=passed, tier=tier,
        findings=findings, run_id=run_path.name, evaluated_at=now_utc(),
    )
    r.signature = sign(r.to_dict())
    return r


def main() -> int:
    # Special-case "sign" subcommand without using argparse subparsers (so positional run_path works).
    argv = sys.argv[1:]
    if argv and argv[0] == "sign":
        sp = argparse.ArgumentParser()
        sp.add_argument("--run", required=True)
        sp.add_argument("--role", required=True, choices=REQUIRED_ROLES)
        sp.add_argument("--signer", required=True)
        a = sp.parse_args(argv[1:])
        payload = sign_for(Path(a.run).expanduser().resolve(), a.role, a.signer)
        print(json.dumps(payload, indent=2))
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
        print(f"[G13 dual_signoff] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
