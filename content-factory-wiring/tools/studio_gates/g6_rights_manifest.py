"""G6 Rights & Legal — every asset has a license + provenance + consent + clearance.

For each asset under media/, output/, audio/, fonts/, music/, sfx/, voices/:
  • An entry must exist in rights_manifest.json keyed by relative path
  • Entry schema:
      {
        "type": "image|audio|video|voice|music|sfx|font|stock",
        "source": "<generator>|<artist>|<library>",
        "model": "<model name + version if AI-gen>",
        "seed": <int|null>,
        "license": "CC0|CC-BY-4.0|MIT|proprietary-licensed|AI-generated-proprietary|public-domain|fair-use|...",
        "license_url": "<verifiable URL>",
        "consent": null | {"signer": "...", "signed_at": "...", "scope": "..."},
        "clearance_status": "cleared|pending|blocked",
        "expires_at": "<ISO date if applicable>"
      }
  • For voice (human likeness) consent MUST be non-null
  • For brand marks shown on-screen, clearance_status must be "cleared"
  • License must be in the allowed list per tier
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import GateFinding, GateResult, now_utc, sign
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign  # type: ignore


ASSET_GLOBS = [
    "media/**/*.{png,jpg,jpeg,webp,mp4,wav,mp3,ogg,m4a,ttf,otf,woff,woff2,svg}",
    "output/**/*.{png,jpg,jpeg,webp,mp4,wav,mp3,m4a,svg}",
    "audio/**/*.{wav,mp3,m4a,ogg}",
    "fonts/**/*.{ttf,otf,woff,woff2}",
    "music/**/*.{wav,mp3,m4a,ogg}",
    "sfx/**/*.{wav,mp3,ogg}",
    "voices/**/*.{wav,mp3,m4a}",
    "scenes/**/*.{png,jpg,mp4,wav}",
]

ALLOWED_LICENSES_PER_TIER: dict[str, set[str]] = {
    "internal": set(),  # internal-only allows everything
    "indie":    {"CC0", "CC-BY-4.0", "MIT", "Apache-2.0", "public-domain", "AI-generated-proprietary", "proprietary-licensed", "fair-use"},
    "aa":       {"CC0", "CC-BY-4.0", "MIT", "Apache-2.0", "public-domain", "AI-generated-proprietary", "proprietary-licensed"},
    "aaa":      {"CC0", "CC-BY-4.0", "MIT", "Apache-2.0", "public-domain", "AI-generated-proprietary", "proprietary-licensed"},
    "live-aaa": {"CC0", "public-domain", "AI-generated-proprietary", "proprietary-licensed"},
}


def _enumerate_assets(run_path: Path) -> set[str]:
    out: set[str] = set()
    for pattern in ASSET_GLOBS:
        # Expand brace-style extensions manually
        base, exts = pattern.split("*.{", 1)
        exts = exts.rstrip("}").split(",")
        for ext in exts:
            for f in run_path.rglob(f"{base.rstrip('/')}/*.{ext.strip()}"):
                if f.is_file() and "_thumb" not in f.name and not f.name.startswith("."):
                    out.add(str(f.relative_to(run_path)))
    return out


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []
    manifest_files = list(run_path.rglob("rights_manifest.json"))

    if not manifest_files:
        # Internal tier may pass without a manifest
        if tier == "internal":
            return _result([], run_path, tier, passed=True)
        findings.append(GateFinding(
            code="G6_no_manifest",
            severity="blocker",
            message="rights_manifest.json missing — required for any external publish",
        ))
        return _result(findings, run_path, tier, passed=False)

    try:
        manifest = json.loads(manifest_files[0].read_text())
    except json.JSONDecodeError as exc:
        findings.append(GateFinding(
            code="G6_manifest_invalid",
            severity="blocker",
            message=f"rights_manifest.json invalid JSON: {exc}",
        ))
        return _result(findings, run_path, tier, passed=False)

    entries: dict[str, dict[str, Any]] = manifest.get("assets") or {}
    asset_paths = _enumerate_assets(run_path)
    allowed = ALLOWED_LICENSES_PER_TIER.get(tier, ALLOWED_LICENSES_PER_TIER["aa"])

    # 1. Missing entries
    for path in sorted(asset_paths):
        if path not in entries:
            findings.append(GateFinding(
                code="G6_asset_unrights_entry",
                severity="blocker",
                message=f"{path} has no rights_manifest entry",
                measurement={"asset": path},
            ))

    now = datetime.now(timezone.utc)
    for asset, entry in entries.items():
        # 2. Required fields
        for required in ("type", "source", "license", "clearance_status"):
            if not entry.get(required):
                findings.append(GateFinding(
                    code="G6_entry_missing_field",
                    severity="blocker",
                    message=f"{asset}: missing rights field `{required}`",
                    measurement={"asset": asset, "missing": required},
                ))

        # 3. License in allowed list
        lic = entry.get("license")
        if allowed and lic and lic not in allowed:
            findings.append(GateFinding(
                code="G6_license_disallowed",
                severity="blocker",
                message=f"{asset}: license `{lic}` not permitted at tier `{tier}`",
                measurement={"asset": asset, "license": lic, "allowed": sorted(allowed)},
            ))

        # 4. Voice / human likeness consent
        if entry.get("type") == "voice" and not entry.get("consent"):
            findings.append(GateFinding(
                code="G6_voice_no_consent",
                severity="blocker",
                message=f"{asset}: voice asset has no consent record",
                measurement={"asset": asset},
            ))

        # 5. Clearance status not "cleared"
        cs = entry.get("clearance_status")
        if cs and cs != "cleared":
            sev = "blocker" if tier in ("aa", "aaa", "live-aaa") else "critical"
            findings.append(GateFinding(
                code="G6_clearance_pending",
                severity=sev,
                message=f"{asset}: clearance_status=`{cs}`",
                measurement={"asset": asset, "clearance_status": cs},
            ))

        # 6. Expiry
        exp = entry.get("expires_at")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if exp_dt < now:
                    findings.append(GateFinding(
                        code="G6_license_expired",
                        severity="blocker",
                        message=f"{asset}: license expired {exp}",
                        measurement={"asset": asset, "expires_at": exp},
                    ))
            except ValueError:
                findings.append(GateFinding(
                    code="G6_expiry_invalid",
                    severity="critical",
                    message=f"{asset}: expires_at unparseable: {exp}",
                ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G6", gate_name="rights_manifest", passed=passed, tier=tier,
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
        print(f"[G6 rights_manifest] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings[:20]:
            print(f"  [{f.severity}] {f.code}: {f.message}")
        if len(r.findings) > 20:
            print(f"  ... and {len(r.findings) - 20} more")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
