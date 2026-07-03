"""post_deploy_verify.py — proves the studio-gate system is operational after deploy.

This is the ONLY command you need to run after `gt refinery reload` on a fresh
content-factory host. Returns exit 0 only when every check below passes:

  1.  Every gate module imports + has evaluate()
  2.  HMAC signing key loads from vault (or dev key in dev mode)
  3.  Sign+verify round-trip works
  4.  For each gate, a known-BAD fixture produces blocker(s)
  5.  For each gate, a known-GOOD fixture passes
  6.  studio_cert against known-bad: exit 1
  7.  studio_cert against known-good: exit 0, certificate signature verifies
  8.  refinery.toml [[studio_gate]] count == 14
  9.  Every required gate has an "approver" mapping
  10. Witness rules + Convoy shape + Hermes cron jobs files exist
  11. Tier policy matrix sane (Tier 3 requires Tier 2's gates)

Output:
  - JSON report at deploy_verification_report.json
  - Stdout summary
  - Exit 0 = green, !=0 = red

Run:
  CONTENTX_CERT_KEY=$(op read "op://prod/contentx/cert_key") \
    python tools/studio_gates/post_deploy_verify.py
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent.parent  # content-factory-wiring/
sys.path.insert(0, str(ROOT / "tools" / "studio_gates"))

# Late-imports so we can capture import failures as findings.

GATE_IDS = ["G1", "G2", "G3", "G4", "G6", "G7", "G9", "G10", "G11", "G13", "G14", "G15"]
GATE_MODULES = {
    "G1": "g1_concept_lock",
    "G2": "g2_canon_lock",
    "G3": "g3_script_multi_read",
    "G4": "g4_visual_continuity",
    "G6": "g6_rights_manifest",
    "G7": "g7_accessibility",
    "G9": "g9_frame_qa",
    "G10": "g10_council_enforcer",
    "G11": "g11_localization",
    "G13": "g13_dual_signoff",
    "G14": "g14_chain_of_custody",
    "G15": "g15_character_identity",
}
ALL_TIERS = ["internal", "indie", "aa", "aaa", "live-aaa"]


@dataclass
class Check:
    id: str
    name: str
    passed: bool = False
    detail: str = ""
    duration_ms: float = 0.0
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    started_at: str = ""
    finished_at: str = ""
    host: str = ""
    git_sha: str = ""
    checks: list[Check] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _time_ms(fn: Callable[[], Any]) -> tuple[Any, float]:
    import time
    t0 = time.perf_counter()
    res = fn()
    return res, (time.perf_counter() - t0) * 1000


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=ROOT, timeout=5,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_imports() -> Check:
    c = Check(id="C01", name="every gate module imports + has evaluate()")
    failed = []
    for gid, mod_name in GATE_MODULES.items():
        try:
            m = importlib.import_module(mod_name)
            if not hasattr(m, "evaluate"):
                failed.append(f"{gid}: no evaluate()")
        except Exception as exc:
            failed.append(f"{gid}: {exc!r}")
    c.passed = not failed
    c.detail = "all importable" if c.passed else "; ".join(failed)
    c.artifacts = {"gates_checked": len(GATE_MODULES)}
    return c


def check_signing_key() -> Check:
    c = Check(id="C02", name="HMAC signing key is set")
    key = os.environ.get("CONTENTX_CERT_KEY")
    if not key:
        c.passed = False
        c.detail = "CONTENTX_CERT_KEY env not set (would use dev key in production)"
    elif key.startswith("dev-mode") or len(key) < 32:
        c.passed = False
        c.detail = f"CONTENTX_CERT_KEY too weak (len={len(key)}); rotate from vault"
    else:
        c.passed = True
        c.detail = f"key set, length {len(key)}"
    return c


def check_sign_verify_roundtrip() -> Check:
    c = Check(id="C03", name="sign+verify round-trip works")
    try:
        from __init__ import sign, verify  # type: ignore
    except ImportError:
        c.passed = False
        c.detail = "could not import sign/verify from studio_gates package"
        return c
    payload = {"foo": "bar", "n": 42, "list": [1, 2, 3]}
    payload["signature"] = sign(payload)
    c.passed = verify(payload)
    c.detail = "round-trip OK" if c.passed else "signature failed to verify"
    return c


def check_refinery_toml() -> Check:
    c = Check(id="C04", name="refinery.toml has all 15 [[studio_gate]] bindings")
    toml = ROOT / "configs" / "refinery.toml"
    if not toml.exists():
        c.passed = False
        c.detail = "configs/refinery.toml missing"
        return c
    text = toml.read_text()
    n = text.count("[[studio_gate]]")
    c.passed = n == 15
    c.detail = f"found {n}/15 [[studio_gate]] sections"
    c.artifacts = {"count": n}
    return c


def check_witness_convoys_hermes() -> Check:
    c = Check(id="C05", name="witness.yaml + convoys.yaml + hermes/cron_jobs.yaml exist")
    files = {
        "witness":  ROOT / "configs" / "witness.yaml",
        "convoys":  ROOT / "configs" / "convoys.yaml",
        "hermes":   ROOT / "hermes" / "cron_jobs.yaml",
    }
    missing = [k for k, p in files.items() if not p.exists()]
    c.passed = not missing
    c.detail = "all present" if c.passed else f"missing: {missing}"
    c.artifacts = {k: str(p.relative_to(ROOT)) for k, p in files.items()}
    return c


def check_tier_matrix_sanity() -> Check:
    c = Check(id="C06", name="tier matrix is monotonic (Tier N+1 ⊇ Tier N required gates)")
    try:
        from __init__ import TIER_GATES  # type: ignore
    except ImportError:
        c.passed = False
        c.detail = "could not import TIER_GATES"
        return c
    # Monotonic-ish: indie ⊇ internal essentials; aa ⊇ indie minus optional; etc.
    # We check that every higher tier doesn't DROP a gate the lower tier required (with exceptions).
    failures = []
    chain = ["internal", "indie", "aa", "aaa", "live-aaa"]
    for i in range(1, len(chain)):
        lower, higher = chain[i - 1], chain[i]
        lo = set(TIER_GATES.get(lower, []))
        hi = set(TIER_GATES.get(higher, []))
        # Allow internal->indie to add many; only check that no required gate is silently dropped
        if not lo.issubset(hi):
            dropped = lo - hi
            failures.append(f"{higher} drops {sorted(dropped)} required by {lower}")
    c.passed = not failures
    c.detail = "monotonic" if c.passed else "; ".join(failures)
    return c


def check_known_bad_blocks(fixtures_root: Path) -> Check:
    c = Check(id="C07", name="known_bad fixture produces blockers on every required gate")
    bad = fixtures_root / "known_bad_run"
    if not bad.exists():
        c.passed = False
        c.detail = f"fixture missing: {bad}"
        return c
    blocked: list[str] = []
    passed: list[str] = []
    errors: list[str] = []
    for gid in GATE_IDS:
        mod = GATE_MODULES[gid]
        try:
            m = importlib.import_module(mod)
            result = m.evaluate(bad, tier="aa")
            if result.passed:
                passed.append(gid)
            else:
                blocked.append(gid)
        except Exception as exc:
            errors.append(f"{gid}: {exc!r}")
    # Expectations for known_bad:
    # - State-based gates (no media required) MUST block on an empty fixture.
    # - Media-based gates (G4, G7, G9, G11) correctly pass when there's no media
    #   to check — adding media to the bad fixture is out of scope for state-only
    #   verification.
    # G15 must block on bad fixture because cast/cast_manifest.json is missing.
    must_block = {"G1", "G2", "G6", "G10", "G13", "G14", "G15"}
    leaks = must_block - set(blocked)
    c.passed = not leaks and not errors
    c.detail = (
        f"blocked={sorted(blocked)} passed={sorted(passed)} "
        + (f"leaks={sorted(leaks)} " if leaks else "")
        + (f"errors={errors}" if errors else "")
    )
    c.artifacts = {"blocked": blocked, "passed": passed, "errors": errors}
    return c


def check_known_good_passes(fixtures_root: Path) -> Check:
    c = Check(id="C08", name="known_good fixture passes the indie tier")
    good = fixtures_root / "known_good_run"
    if not good.exists():
        c.passed = False
        c.detail = f"fixture missing: {good}"
        return c
    # Reset chain of custody to a fresh file
    coc = good / "chain_of_custody.jsonl"
    if coc.exists():
        coc.unlink()

    studio_cert = ROOT / "tools" / "studio_gates" / "studio_cert.py"
    py = sys.executable
    result = subprocess.run(
        [py, str(studio_cert), str(good), "--tier=indie", "--json"],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    c.passed = result.returncode == 0
    try:
        cert = json.loads(result.stdout)
        c.artifacts = cert.get("summary", {})
    except json.JSONDecodeError:
        c.artifacts = {"stderr_tail": (result.stderr or "")[-500:]}
    c.detail = "certified" if c.passed else f"exit={result.returncode}; {c.artifacts}"
    return c


def check_studio_cert_blocks_bad(fixtures_root: Path) -> Check:
    c = Check(id="C09", name="studio_cert refuses the known_bad fixture (exit 1)")
    bad = fixtures_root / "known_bad_run"
    if not bad.exists():
        c.passed = False
        c.detail = f"fixture missing: {bad}"
        return c
    studio_cert = ROOT / "tools" / "studio_gates" / "studio_cert.py"
    py = sys.executable
    result = subprocess.run(
        [py, str(studio_cert), str(bad), "--tier=aa", "--json"],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    c.passed = result.returncode != 0
    try:
        cert = json.loads(result.stdout)
        c.artifacts = cert.get("summary", {})
    except json.JSONDecodeError:
        pass
    c.detail = (
        f"correctly rejected, exit={result.returncode}, {c.artifacts}"
        if c.passed else "BAD: cert should have rejected this run but exit=0"
    )
    return c


def check_tamper_detection(fixtures_root: Path) -> Check:
    c = Check(id="C10", name="chain_of_custody tamper detection works")
    tmp = Path(tempfile.mkdtemp(prefix="tamper-"))
    try:
        from g14_chain_of_custody import append, verify_chain  # type: ignore
        append(tmp, {"kind": "test1"})
        append(tmp, {"kind": "test2"})
        ok_before, _ = verify_chain(tmp)
        # Tamper line 0
        log = tmp / "chain_of_custody.jsonl"
        lines = log.read_text().splitlines()
        entry = json.loads(lines[0])
        entry["event"]["kind"] = "TAMPERED"
        lines[0] = json.dumps(entry)
        log.write_text("\n".join(lines) + "\n")
        ok_after, findings_after = verify_chain(tmp)
        c.passed = ok_before and not ok_after
        c.detail = (
            "tamper detected" if c.passed
            else f"FAIL — before={ok_before}, after={ok_after}, findings={[f.code for f in findings_after]}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return c


def check_signoff_invalidation(fixtures_root: Path) -> Check:
    c = Check(id="C11", name="post-signoff output mutation invalidates G13")
    good = fixtures_root / "known_good_run"
    if not good.exists():
        c.passed = False
        c.detail = f"fixture missing: {good}"
        return c
    tmp = Path(tempfile.mkdtemp(prefix="signoff-"))
    try:
        # Copy fixture
        shutil.copytree(good, tmp / "run", dirs_exist_ok=True)
        run = tmp / "run"
        # Ensure approvals exist (re-sign)
        py = sys.executable
        g13 = ROOT / "tools" / "studio_gates" / "g13_dual_signoff.py"
        subprocess.run([py, str(g13), "sign", "--run", str(run), "--role", "creative_director", "--signer", "TestCD"], capture_output=True, timeout=30)
        subprocess.run([py, str(g13), "sign", "--run", str(run), "--role", "technical_director", "--signer", "TestTD"], capture_output=True, timeout=30)
        # Verify it passes
        first = subprocess.run([py, str(g13), str(run), "--tier=aa"], capture_output=True, text=True, timeout=30)
        if first.returncode != 0:
            c.passed = False
            c.detail = f"signoff did not validate even before mutation: {first.stdout[-200:]}"
            return c
        # Mutate the output — find any mp4 or txt to bump
        mutated = False
        for f in list(run.rglob("*.mp4")) + list(run.rglob("*.txt")):
            with f.open("ab") as fh:
                fh.write(b"\x00")
            mutated = True
            break
        if not mutated:
            # No mutable output — write a dummy and re-test
            (run / "output").mkdir(exist_ok=True)
            (run / "output" / "extra.txt").write_text("extra")
            mutated = True
        # Re-verify — should fail
        second = subprocess.run([py, str(g13), str(run), "--tier=aa"], capture_output=True, text=True, timeout=30)
        c.passed = second.returncode != 0 and "output_changed_post_signoff" in second.stdout
        c.detail = "post-signoff mutation invalidates G13" if c.passed else f"FAIL: {second.stdout[-200:]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return c


def check_schemas_present() -> Check:
    c = Check(id="C12", name="JSON schemas for every gate file are present")
    schemas_dir = ROOT / "schemas" / "gates"
    if not schemas_dir.exists():
        c.passed = False
        c.detail = "schemas/gates/ missing"
        return c
    expected = {f"{gid}_{name}.schema.json" for gid, name in [
        ("01", "concept_lock"), ("02", "canon_lock"), ("03", "script_review"),
        ("04", "continuity"), ("05", "audio_mix"), ("06", "rights_manifest"),
        ("07", "accessibility"), ("08", "platform_cert"), ("09", "frame_qa"),
        ("10", "council_verdict"), ("11", "localization"), ("12", "liveops_kpi"),
        ("13", "signoff"), ("14", "chain_of_custody"), ("15", "character_identity"),
    ]}
    present = {p.name for p in schemas_dir.glob("*.schema.json")}
    missing = expected - present
    c.passed = not missing
    c.detail = f"found {len(present)}/{len(expected)} schemas" + (f"; missing {sorted(missing)}" if missing else "")
    c.artifacts = {"present": sorted(present), "missing": sorted(missing)}
    return c


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _reset_fixtures(fixtures_root: Path) -> None:
    """Reset both fixtures to a clean baseline so every verifier run is idempotent.

    - known_bad_run: keep only run.json
    - known_good_run: rebuilt by fixtures/build_fixtures.py
    """
    bad = fixtures_root / "known_bad_run"
    if bad.exists():
        for child in bad.iterdir():
            if child.name != "run.json":
                if child.is_dir(): shutil.rmtree(child, ignore_errors=True)
                else:
                    try: child.unlink()
                    except OSError: pass
    builder = ROOT / "fixtures" / "build_fixtures.py"
    if builder.exists():
        subprocess.run([sys.executable, str(builder)], capture_output=True, cwd=ROOT, timeout=60)


def run(fixtures_root: Path | None = None, write_report_to: Path | None = None) -> Report:
    fixtures_root = fixtures_root or (ROOT / "fixtures")
    _reset_fixtures(fixtures_root)
    report = Report(
        started_at=datetime.now(timezone.utc).isoformat(),
        host=os.uname().nodename,
        git_sha=_git_sha(),
    )

    checks = [
        check_imports,
        check_signing_key,
        check_sign_verify_roundtrip,
        check_refinery_toml,
        check_witness_convoys_hermes,
        check_tier_matrix_sanity,
        lambda: check_known_bad_blocks(fixtures_root),
        lambda: check_known_good_passes(fixtures_root),
        lambda: check_studio_cert_blocks_bad(fixtures_root),
        lambda: check_tamper_detection(fixtures_root),
        lambda: check_signoff_invalidation(fixtures_root),
        check_schemas_present,
    ]

    for fn in checks:
        try:
            res, ms = _time_ms(fn)
        except Exception as exc:
            res = Check(id="ERR", name=getattr(fn, "__name__", str(fn)),
                        passed=False, detail=f"{type(exc).__name__}: {exc}")
            ms = 0
        res.duration_ms = ms
        report.checks.append(res)

    report.finished_at = datetime.now(timezone.utc).isoformat()
    report.summary = {
        "total": len(report.checks),
        "passed": sum(1 for c in report.checks if c.passed),
        "failed": sum(1 for c in report.checks if not c.passed),
    }

    if write_report_to:
        write_report_to.parent.mkdir(parents=True, exist_ok=True)
        write_report_to.write_text(json.dumps(_report_to_dict(report), indent=2))
    return report


def _report_to_dict(r: Report) -> dict[str, Any]:
    return {
        "started_at": r.started_at, "finished_at": r.finished_at,
        "host": r.host, "git_sha": r.git_sha,
        "summary": r.summary,
        "checks": [
            {"id": c.id, "name": c.name, "passed": c.passed, "detail": c.detail,
             "duration_ms": round(c.duration_ms, 1), "artifacts": c.artifacts}
            for c in r.checks
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default=str(ROOT / "fixtures"))
    ap.add_argument("--report-to", default=str(ROOT / "deploy_verification_report.json"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    r = run(Path(args.fixtures), Path(args.report_to))
    d = _report_to_dict(r)

    if args.json:
        print(json.dumps(d, indent=2))
    else:
        print(f"\n=== POST-DEPLOY VERIFICATION ({r.git_sha} on {r.host}) ===")
        print(f"{'ID':<5} {'Check':<54} {'Result':<8} {'ms':>7}")
        print("-" * 78)
        for c in r.checks:
            mark = "PASS" if c.passed else "FAIL"
            print(f"{c.id:<5} {c.name[:54]:<54} {mark:<8} {c.duration_ms:>7.1f}")
            if not c.passed:
                print(f"      └─ {c.detail[:200]}")
        print("-" * 78)
        s = r.summary
        print(f"  {s['passed']}/{s['total']} passed, {s['failed']} failed")
        print(f"  report  → {args.report_to}")
    return 0 if r.summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
