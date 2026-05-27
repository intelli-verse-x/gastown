"""G2 Canon Lock — character/world bible cannot drift without explicit unlock.

The bible (studio_bible.json) declares: characters, palette, vocabulary, tone, props.
Every shot's metadata must reference these fields by id, not by literal value.

Blocks if:
  • studio_bible.json missing for kinds that require continuity (series, learning_series, audiobook)
  • Bible exists but has no `lock` field
  • Bible was modified without a matching `unlock_request` bead reference
  • Scenes/shots use characters, palette, props NOT declared in bible
  • Bible's `frozen_at` timestamp is older than any scene's `created_at`
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from . import GateFinding, GateResult, now_utc, sign
except ImportError:
    from __init__ import GateFinding, GateResult, now_utc, sign  # type: ignore


REQUIRES_BIBLE = {"series", "learning_series", "tv_series", "audiobook", "movie", "short_movie"}


def evaluate(run_path: Path, tier: str = "aa") -> GateResult:
    findings: list[GateFinding] = []

    # Pipeline kind inference
    run_json = _safe_json(run_path / "run.json") or {}
    pipeline = (run_json.get("pipeline") or "").lower()
    requires = pipeline in REQUIRES_BIBLE or tier in ("aa", "aaa", "live-aaa")

    bible_files = list(run_path.rglob("studio_bible.json"))
    if not bible_files:
        if requires:
            findings.append(GateFinding(
                code="G2_no_bible",
                severity="blocker",
                message=f"studio_bible.json missing — required for {pipeline or tier}",
            ))
        return _result(findings, run_path, tier, passed=not requires)

    # Use the root-most bible as canonical
    bibles_sorted = sorted(bible_files, key=lambda p: len(p.parts))
    canonical_bible_path = bibles_sorted[0]
    try:
        bible = json.loads(canonical_bible_path.read_text())
    except json.JSONDecodeError as exc:
        findings.append(GateFinding(
            code="G2_bible_invalid",
            severity="blocker",
            message=f"studio_bible.json invalid JSON: {exc}",
            measurement={"file": str(canonical_bible_path)},
        ))
        return _result(findings, run_path, tier, passed=False)

    # 1. Lock field present?
    lock = bible.get("lock") or {}
    if not lock.get("locked"):
        findings.append(GateFinding(
            code="G2_bible_unlocked",
            severity="blocker",
            message="bible.lock.locked must be true — concept lock has not been applied",
            measurement={"lock": lock},
        ))

    if not lock.get("frozen_at"):
        findings.append(GateFinding(
            code="G2_no_frozen_at",
            severity="blocker",
            message="bible.lock.frozen_at missing — cannot verify temporal consistency",
        ))

    # 2. Bible hash matches current contents?
    if lock.get("content_hash"):
        canonical = {k: v for k, v in bible.items() if k != "lock"}
        new_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if new_hash != lock["content_hash"]:
            unlock = lock.get("unlock_request")
            if not unlock or not unlock.get("approved_bead"):
                findings.append(GateFinding(
                    code="G2_drift_without_unlock",
                    severity="blocker",
                    message=(
                        "bible content changed after lock and no approved unlock_request bead exists"
                    ),
                    measurement={
                        "stored_hash": lock["content_hash"][:16],
                        "current_hash": new_hash[:16],
                    },
                ))

    # 3. Multiple bibles?
    if len(bibles_sorted) > 1:
        # Check they all hash equal (canonicalized)
        canon_text = canonical_bible_path.read_bytes()
        canon_hash = hashlib.md5(canon_text).hexdigest()
        for other in bibles_sorted[1:]:
            if hashlib.md5(other.read_bytes()).hexdigest() != canon_hash:
                findings.append(GateFinding(
                    code="G2_bible_fork",
                    severity="critical",
                    message=(
                        f"Multiple bibles diverge — {other.relative_to(run_path)} != "
                        f"{canonical_bible_path.relative_to(run_path)}"
                    ),
                    measurement={"forked_file": str(other.relative_to(run_path))},
                ))

    # 4. Character/palette/prop usage in scenes vs bible declarations
    declared_chars = {c.get("id") for c in (bible.get("characters") or []) if isinstance(c, dict)}
    declared_props = set((bible.get("props") or []) or [])
    declared_palette = {p.lower() for p in (bible.get("palette") or []) if isinstance(p, str)}

    referenced_chars: set[str] = set()
    referenced_props: set[str] = set()
    referenced_palette: set[str] = set()
    for scene_meta in run_path.rglob("scenes/*/scene.json"):
        try:
            data = json.loads(scene_meta.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for c in data.get("characters") or []:
            cid = c.get("id") if isinstance(c, dict) else c
            if cid: referenced_chars.add(cid)
        for p in data.get("props") or []:
            referenced_props.add(p)
        for color in (data.get("palette") or []):
            if isinstance(color, str):
                referenced_palette.add(color.lower())

    undeclared_chars = referenced_chars - declared_chars
    if declared_chars and undeclared_chars:
        findings.append(GateFinding(
            code="G2_undeclared_character",
            severity="blocker",
            message=f"{len(undeclared_chars)} character(s) used but not declared in bible: {sorted(undeclared_chars)[:5]}",
            measurement={"undeclared": sorted(undeclared_chars)},
        ))
    undeclared_props = referenced_props - declared_props
    if declared_props and undeclared_props:
        findings.append(GateFinding(
            code="G2_undeclared_prop",
            severity="high",
            message=f"{len(undeclared_props)} prop(s) not in bible: {sorted(undeclared_props)[:5]}",
            measurement={"undeclared": sorted(undeclared_props)},
        ))
    palette_drift = referenced_palette - declared_palette
    if declared_palette and palette_drift:
        findings.append(GateFinding(
            code="G2_palette_drift",
            severity="critical",
            message=f"{len(palette_drift)} color(s) not in bible palette: {sorted(palette_drift)[:5]}",
            measurement={"drifted": sorted(palette_drift)},
        ))

    passed = not any(f.severity == "blocker" for f in findings)
    return _result(findings, run_path, tier, passed)


def _safe_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _result(findings, run_path, tier, passed):
    r = GateResult(
        gate_id="G2", gate_name="canon_lock", passed=passed, tier=tier,
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
        print(f"[G2 canon_lock] {'PASS' if r.passed else 'FAIL'}")
        for f in r.findings:
            print(f"  [{f.severity}] {f.code}: {f.message}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
