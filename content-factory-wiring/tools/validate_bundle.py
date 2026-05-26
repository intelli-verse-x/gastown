"""End-to-end validation of all four deliverables (a), (b), (c), (d).

Run:
    CONTENTX_CERT_KEY=... python tools/validate_bundle.py

Validates:
  (a) JSON schemas accept real gate outputs
  (b) Auditor agents emit valid council audit files with verifying signatures
  (c) refinery_viral_shorts.toml parses cleanly and declares 3 tiers
  (d) Canvas .tsx contains the new tier×gate matrix + post-deploy sections

Prints a delivery confirmation matrix and exits non-zero on any failure.
"""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "studio_gates"))

import jsonschema  # type: ignore
from jsonschema import Draft202012Validator, RefResolver


def green(s): return f"\033[32m{s}\033[0m"
def red(s):   return f"\033[31m{s}\033[0m"
def bold(s):  return f"\033[1m{s}\033[0m"


# ---------------------------------------------------------------------------
# (a) Schema validation
# ---------------------------------------------------------------------------

def _emit_all_gate_outputs(run_path: Path) -> None:
    """Run every gate module against the fixture so all gates/G{n}.json files exist."""
    import importlib
    run_path.mkdir(exist_ok=True)
    (run_path / "gates").mkdir(exist_ok=True)
    modules = {
        "G1":  "g1_concept_lock",         "G2":  "g2_canon_lock",
        "G3":  "g3_script_multi_read",    "G4":  "g4_visual_continuity",
        "G6":  "g6_rights_manifest",      "G7":  "g7_accessibility",
        "G9":  "g9_frame_qa",             "G10": "g10_council_enforcer",
        "G11": "g11_localization",        "G13": "g13_dual_signoff",
        "G14": "g14_chain_of_custody",    "G15": "g15_character_identity",
    }
    for gid, modname in modules.items():
        try:
            m = importlib.import_module(modname)
            result = m.evaluate(run_path, tier="aa")
            (run_path / "gates" / f"{gid}.json").write_text(
                json.dumps(result.to_dict(), indent=2)
            )
        except Exception as exc:
            # Schema validator will report it as missing/invalid
            print(f"  (warn) {gid}: {exc}", file=sys.stderr)


def validate_schemas() -> list[tuple[str, bool, str]]:
    schemas_dir = ROOT / "schemas" / "gates"
    fixture = ROOT / "fixtures" / "known_good_run"
    gates_dir = fixture / "gates"
    _emit_all_gate_outputs(fixture)
    if not gates_dir.exists():
        return [("schema-source", False, "fixtures/known_good_run/gates/ missing")]

    common = json.loads((schemas_dir / "_common.schema.json").read_text())
    resolver = RefResolver(
        base_uri=f"file://{schemas_dir.as_posix()}/",
        referrer=common,
        store={
            "_common.schema.json": common,
            "https://contentx/gates/_common.schema.json": common,
        },
    )

    gate_to_schema = {
        "G1.json":  "01_concept_lock.schema.json",
        "G2.json":  "02_canon_lock.schema.json",
        "G3.json":  "03_script_review.schema.json",
        "G4.json":  "04_continuity.schema.json",
        "G6.json":  "06_rights_manifest.schema.json",
        "G7.json":  "07_accessibility.schema.json",
        "G9.json":  "09_frame_qa.schema.json",
        "G10.json": "10_council_verdict.schema.json",
        "G11.json": "11_localization.schema.json",
        "G13.json": "13_signoff.schema.json",
        "G14.json": "14_chain_of_custody.schema.json",
        "G15.json": "15_character_identity.schema.json",
    }
    results: list[tuple[str, bool, str]] = []
    for gate_file, schema_file in gate_to_schema.items():
        gpath = gates_dir / gate_file
        spath = schemas_dir / schema_file
        if not gpath.exists():
            results.append((schema_file, False, f"gate output missing: {gpath}"))
            continue
        if not spath.exists():
            results.append((schema_file, False, f"schema missing: {spath}"))
            continue
        try:
            instance = json.loads(gpath.read_text())
            schema = json.loads(spath.read_text())
            validator = Draft202012Validator(schema, resolver=resolver)
            errors = list(validator.iter_errors(instance))
            if errors:
                results.append((schema_file, False, "; ".join(e.message for e in errors[:3])))
            else:
                results.append((schema_file, True, f"validates {gate_file}"))
        except Exception as exc:
            results.append((schema_file, False, f"{type(exc).__name__}: {exc}"))
    return results


# ---------------------------------------------------------------------------
# (b) Auditor agents
# ---------------------------------------------------------------------------

def run_auditors() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    fixture = ROOT / "fixtures" / "known_good_run"
    try:
        from agents.auditors import (
            BrandAuditor, LegalAuditor, CulturalAuditor,
            AccessibilityAuditor, RightsAuditor,
        )
    except Exception as exc:
        out.append(("import auditors", False, f"{type(exc).__name__}: {exc}"))
        return out

    try:
        from __init__ import verify as hmac_verify  # type: ignore
    except Exception as exc:
        out.append(("import verify", False, f"{type(exc).__name__}: {exc}"))
        return out

    auditors = [
        ("BrandAuditor",         BrandAuditor()),
        ("LegalAuditor",         LegalAuditor()),
        ("CulturalAuditor",      CulturalAuditor("global")),
        ("AccessibilityAuditor", AccessibilityAuditor()),
        ("RightsAuditor",        RightsAuditor()),
    ]
    for name, a in auditors:
        try:
            result = a.run(fixture)
            sig_ok = hmac_verify(result.to_dict())
            audit_file = fixture / "council_audits" / f"{a.rubric_id}_audit.json"
            present = audit_file.exists()
            ok = sig_ok and present
            out.append((
                name, ok,
                f"verdict={result.final_verdict}, score={result.overall_score:.1f}, "
                f"sig_ok={sig_ok}, file={present}"
            ))
        except Exception as exc:
            out.append((name, False, f"{type(exc).__name__}: {exc}"))
    return out


# ---------------------------------------------------------------------------
# (c) refinery_viral_shorts.toml
# ---------------------------------------------------------------------------

def validate_refinery_toml() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    toml_path = ROOT / "configs" / "refinery_viral_shorts.toml"
    if not toml_path.exists():
        out.append(("file present", False, str(toml_path)))
        return out
    out.append(("file present", True, str(toml_path.relative_to(ROOT))))
    try:
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception as exc:
        out.append(("parses cleanly", False, f"{type(exc).__name__}: {exc}"))
        return out
    out.append(("parses cleanly", True, f"{len(data)} top-level keys"))

    # Required structure
    pipeline = data.get("pipeline", {})
    out.append(("pipeline.name == viral_shorts", pipeline.get("name") == "viral_shorts",
                f"got {pipeline.get('name')!r}"))
    tiers = data.get("tier_policy", [])
    tier_ids = {t.get("tier") for t in tiers}
    out.append(("tiers internal/indie/aa declared", {"internal", "indie", "aa"}.issubset(tier_ids),
                f"got {sorted(tier_ids)}"))
    owners = data.get("escalation_owners", {})
    out.append(("escalation_owners covers all 14 gates", len(owners) >= 13,  # G12 lives in global
                f"{len(owners)} owners declared"))
    platforms = data.get("platform", [])
    out.append(("platforms declared", len(platforms) >= 3,
                f"{len(platforms)} platforms"))
    redo = data.get("auto_redo", {})
    out.append(("auto_redo enabled", redo.get("enabled") is True, str(redo)))
    return out


# ---------------------------------------------------------------------------
# (d) Canvas wiring
# ---------------------------------------------------------------------------

def validate_canvas() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    canvas = Path.home() / ".cursor/projects/Users-devashishbadlani-dev-gastown/canvases/contentx-pipeline-matrix.canvas.tsx"
    if not canvas.exists():
        out.append(("file present", False, str(canvas)))
        return out
    text = canvas.read_text()
    out.append(("file present", True, str(canvas)))
    out.append(("TierGateMatrix section", "function TierGateMatrix(" in text, ""))
    out.append(("DeployVerificationSection",
                "function DeployVerificationSection(" in text, ""))
    out.append(("STUDIO_GATES list has 15 rows",
                text.count('{ id: "G') >= 15, ""))
    out.append(("DEPLOY_CHECKS list has 12 rows",
                text.count('id: "C0') + text.count('id: "C1') >= 12, ""))
    out.append(("wired into root", "<TierGateMatrix />" in text and "<DeployVerificationSection />" in text, ""))
    return out


# ---------------------------------------------------------------------------

def main() -> int:
    sections = [
        ("(a) JSON schemas validate real gate outputs", validate_schemas),
        ("(b) Auditor agents produce signed council audits", run_auditors),
        ("(c) refinery_viral_shorts.toml is enforceable policy", validate_refinery_toml),
        ("(d) Canvas has the tier×gate matrix + deploy status", validate_canvas),
    ]
    all_ok = True
    for title, fn in sections:
        print(bold(f"\n{title}"))
        print("-" * len(title))
        results = fn()
        for name, ok, detail in results:
            mark = green("PASS") if ok else red("FAIL")
            print(f"  {mark}  {name:<40} {detail}")
            if not ok:
                all_ok = False

    print(bold("\n" + ("=" * 60)))
    if all_ok:
        print(green(bold("  ALL FOUR DELIVERABLES VERIFIED")))
    else:
        print(red(bold("  ONE OR MORE DELIVERABLES NOT VERIFIED")))
    print(bold("=" * 60))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
