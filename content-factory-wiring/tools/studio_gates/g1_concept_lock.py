"""G1 Concept Lock — pitch deck must be approved before scripting starts.

Blocks if:
  • metadata/pitch_deck.json doesn't exist
  • pitch_deck.json missing `approvals.creative_director` OR `approvals.technical_director`
  • approval timestamps are older than pitch_deck modification time (stale approval)
  • approval signatures don't verify against HMAC key

Refinery binds this gate to the ideation→script transition.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import GateFinding, GateResult, now_utc, sign, verify
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign, verify  # type: ignore


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    pitch_files = list(run_path.rglob("pitch_deck.json")) + list(run_path.rglob("metadata/pitch_deck.json"))
    if not pitch_files:
        findings.append(GateFinding(
            code="G1_no_pitch",
            severity="blocker",
            message="No pitch_deck.json found — concept must be locked before scripting.",
            measurement={"searched": str(run_path)},
        ))
        return _result(findings, run_path, tier, passed=False)

    pitch_file = pitch_files[0]
    try:
        pitch = json.loads(pitch_file.read_text())
    except json.JSONDecodeError as exc:
        findings.append(GateFinding(
            code="G1_pitch_invalid",
            severity="blocker",
            message=f"pitch_deck.json is not valid JSON: {exc}",
            measurement={"file": str(pitch_file)},
        ))
        return _result(findings, run_path, tier, passed=False)

    approvals = pitch.get("approvals") or {}

    # 1. Both signatures present?
    for role in ("creative_director", "technical_director"):
        sig = approvals.get(role)
        if not sig:
            findings.append(GateFinding(
                code="G1_missing_approval",
                severity="blocker",
                message=f"approvals.{role} missing — required for concept lock",
                measurement={"role": role},
            ))
        elif not all(k in sig for k in ("signer", "signed_at", "signature")):
            findings.append(GateFinding(
                code="G1_malformed_approval",
                severity="blocker",
                message=f"approvals.{role} missing required fields (signer, signed_at, signature)",
                measurement={"role": role, "have": list(sig.keys())},
            ))

    # 2. Signatures verify?
    for role, sig in approvals.items():
        if not isinstance(sig, dict):
            continue
        payload = {
            "role": role,
            "signer": sig.get("signer"),
            "signed_at": sig.get("signed_at"),
            "pitch_hash": pitch.get("hash"),
            "signature": sig.get("signature"),
        }
        if not verify(payload):
            findings.append(GateFinding(
                code="G1_signature_invalid",
                severity="blocker",
                message=f"approvals.{role} signature did not verify against HMAC key",
                measurement={"role": role, "signer": sig.get("signer")},
            ))

    # 3. Stale approval (pitch mutated after approval)?
    if pitch.get("hash"):
        # Re-hash current pitch contents (excluding approvals + hash itself)
        canonical = {k: v for k, v in pitch.items() if k not in ("approvals", "hash")}
        import hashlib
        new_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if new_hash != pitch["hash"]:
            findings.append(GateFinding(
                code="G1_stale_approval",
                severity="blocker",
                message="pitch_deck was modified after approvals were signed — re-approve required",
                measurement={"stored_hash": pitch["hash"][:16], "recomputed": new_hash[:16]},
            ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G1", gate_name="concept_lock", passed=passed, tier=tier,
        findings=findings, run_id=run_path.name, evaluated_at=now_utc(),
    )
    r.signature = sign(r.to_dict())
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_path")
    ap.add_argument("--tier", default="aa")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = evaluate(Path(args.run_path).expanduser().resolve(), args.tier)
    if args.json:
        print(json.dumps(r.to_dict(), indent=2))
    else:
        print(f"[G1 concept_lock] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
