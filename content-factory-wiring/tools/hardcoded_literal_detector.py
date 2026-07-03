"""
hardcoded_literal_detector.py — find every site in content-factory's source tree where
narrator_style / mood / color_tone / aspect_ratio / duration_seconds is hardcoded
instead of being routed through the PipelineContext primitive.

The team's own PIPELINE_CONTEXT_GAP_ANALYSIS lists these counts:
  • narrator_style hardcoded in 24 files
  • mood / color_tone in 6 sites
  • aspect_ratio in 10 files (19 literals)
  • duration_seconds in 17 files (~39 literals)
  • visual_style derivation (GAP-7) — outstanding

This script verifies those numbers, finds the exact file:line, and emits
both a JSON gap report and a bd-create script that opens one bug per file.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


@dataclass
class Hit:
    file: str
    line: int
    snippet: str
    category: str
    severity: str


# Regex patterns: detect literal assignments that should flow from PipelineContext
PATTERNS: dict[str, list[tuple[str, str]]] = {
    "narrator_style": [
        (r'narrator_style\s*[=:]\s*["\']([^"\']+)["\']', "string literal"),
        (r'"narrator_style"\s*:\s*"([^"]+)"', "json literal"),
    ],
    "mood": [
        (r'\bmood\s*[=:]\s*["\']([^"\']+)["\']', "string literal"),
        (r'"mood"\s*:\s*"([^"]+)"', "json literal"),
        (r'\bcolor_tone\s*[=:]\s*["\']([^"\']+)["\']', "string literal"),
    ],
    "aspect_ratio": [
        (r'\baspect_ratio\s*[=:]\s*["\']([^"\']+)["\']', "string literal"),
        (r'"aspect_ratio"\s*:\s*"([^"]+)"', "json literal"),
        (r'\baspect\s*=\s*["\']([0-9]+:[0-9]+)["\']', "string literal"),
    ],
    "duration_seconds": [
        (r'\bduration_seconds\s*[=:]\s*([0-9]+\.?[0-9]*)', "numeric literal"),
        (r'"duration_seconds"\s*:\s*([0-9]+\.?[0-9]*)', "json literal"),
        (r'\bduration\s*=\s*([0-9]+\.?[0-9]*)\s*[,\)#]', "numeric literal"),
    ],
    "visual_style": [
        (r'\bvisual_style\s*[=:]\s*["\']([^"\']+)["\']', "string literal"),
        (r'"visual_style"\s*:\s*"([^"]+)"', "json literal"),
    ],
}

# Strings that indicate "this is from PipelineContext, not hardcoded"
ALLOWLIST_PATTERNS = [
    r"context\.",
    r"ctx\.",
    r"pipeline_context\.",
    r"PipelineContext\(",
    r"\.get\(",  # likely env/config fetch
    r"\.merged\(",
    r"# noqa: hardcode",
]

# Skip dirs
SKIP_DIRS = {".venv", "venv", "node_modules", ".git", "__pycache__", "dist", "build",
             ".working_dir", "out", ".firecrawl", ".cursor", "logs"}


def scan(root: Path) -> list[Hit]:
    hits: list[Hit] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(d in path.parts for d in SKIP_DIRS):
            continue
        if path.suffix not in (".py", ".json", ".yaml", ".yml", ".toml"):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        # Skip very large files
        if len(text) > 2_000_000:
            continue
        for category, pats in PATTERNS.items():
            for pat, _kind in pats:
                for m in re.finditer(pat, text):
                    # Find line number
                    line_no = text[: m.start()].count("\n") + 1
                    # Pull surrounding line
                    line_start = text.rfind("\n", 0, m.start()) + 1
                    line_end = text.find("\n", m.end())
                    if line_end == -1:
                        line_end = len(text)
                    snippet = text[line_start:line_end].strip()
                    # Allowlist
                    if any(re.search(p, snippet) for p in ALLOWLIST_PATTERNS):
                        continue
                    hits.append(Hit(
                        file=str(path.relative_to(root)),
                        line=line_no,
                        snippet=snippet[:200],
                        category=category,
                        severity="high",
                    ))
    return hits


def summarize(hits: list[Hit]) -> dict[str, dict[str, int]]:
    by_cat: dict[str, dict[str, int]] = {}
    for h in hits:
        cat = by_cat.setdefault(h.category, {"hits": 0, "files": 0})
        cat["hits"] += 1
    # Count distinct files per category
    files_per_cat: dict[str, set[str]] = {}
    for h in hits:
        files_per_cat.setdefault(h.category, set()).add(h.file)
    for cat, files in files_per_cat.items():
        by_cat[cat]["files"] = len(files)
    return by_cat


def emit_beads(hits: list[Hit], out: Path) -> int:
    # One bd per file per category (avoid 100s of tiny beads)
    grouped: dict[tuple[str, str], list[Hit]] = {}
    for h in hits:
        grouped.setdefault((h.file, h.category), []).append(h)
    n = 0
    with out.open("w") as fh:
        for (file, category), hs in grouped.items():
            args = {
                "type": "bug",
                "priority": "2",
                "title": f"Hardcoded {category} in {file} ({len(hs)} site(s))",
                "labels": ["content-factory", "pipeline-context", "hardcoded-literal", category],
                "description": (
                    f"PIPELINE_CONTEXT_GAP_ANALYSIS calls for {category} to be routed "
                    f"through PipelineContext. This file has {len(hs)} hardcoded site(s):\n\n"
                    + "\n".join(f"  L{h.line}: {h.snippet}" for h in hs[:10])
                    + (f"\n  …and {len(hs)-10} more" if len(hs) > 10 else "")
                ),
            }
            fh.write(json.dumps(args) + "\n")
            n += 1
    return n


def emit_bd_script(hits: list[Hit], out: Path) -> int:
    grouped: dict[tuple[str, str], list[Hit]] = {}
    for h in hits:
        grouped.setdefault((h.file, h.category), []).append(h)
    lines = [
        "#!/usr/bin/env bash",
        "# Auto-generated by hardcoded_literal_detector.py",
        "# Requires: bd installed (`go install github.com/steveyegge/beads/cmd/bd@latest`)",
        "set -euo pipefail",
        "",
    ]
    for (file, category), hs in grouped.items():
        title = f"Hardcoded {category} in {file} ({len(hs)} site(s))"
        desc = (
            f"Route {category} through PipelineContext. Sites:\\n"
            + "\\n".join(f"L{h.line}: {h.snippet[:80]}" for h in hs[:5])
        )
        lines.append(
            f'bd create {json.dumps(title)} '
            f'--type=bug --priority=2 '
            f'--labels=content-factory,pipeline-context,hardcoded-literal,{category} '
            f'--description={json.dumps(desc)}'
        )
    out.write_text("\n".join(lines) + "\n")
    out.chmod(0o755)
    return len(lines) - 5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", default="/Users/devashishbadlani/dev/content-factory", nargs="?")
    ap.add_argument("--out", default="hardcoded_literals.json")
    ap.add_argument("--emit-beads", help="write beads.jsonl")
    ap.add_argument("--emit-bd-script", help="write bd create script")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    hits = scan(root)
    summary = summarize(hits)
    report = {
        "root": str(root),
        "total_hits": len(hits),
        "summary_by_category": summary,
        "hits": [asdict(h) for h in hits],
    }
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"\nFound {len(hits)} hardcoded sites:")
    for cat, c in sorted(summary.items()):
        print(f"  {cat:<20} {c['hits']:>4} hits across {c['files']:>3} files")
    print(f"\nreport -> {args.out}")

    if args.emit_beads:
        n = emit_beads(hits, Path(args.emit_beads))
        print(f"beads -> {args.emit_beads} ({n} beads)")
    if args.emit_bd_script:
        n = emit_bd_script(hits, Path(args.emit_bd_script))
        print(f"bd-script -> {args.emit_bd_script} ({n} commands)")


if __name__ == "__main__":
    main()
