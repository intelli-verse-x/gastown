"""Character consistency subsystem (public re-export).

The actual types live in ``_models`` to avoid collision with
``tools/studio_gates/__init__.py`` (both sit on sys.path when G15 runs).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sibling modules importable when this package is imported by absolute path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _models import (  # type: ignore  # noqa: E402,F401
    CHARACTER_TYPES,
    OutfitState,
    CharacterCanonical,
    CastMember,
    CastScene,
    CastManifest,
    default_registry_root,
    sign,
    verify,
    now_utc,
)

__all__ = [
    "CHARACTER_TYPES",
    "OutfitState", "CharacterCanonical", "CastMember", "CastScene", "CastManifest",
    "default_registry_root", "sign", "verify", "now_utc",
]
