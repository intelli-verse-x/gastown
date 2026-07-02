"""Character consistency subsystem.

The registry is the single source of truth for every character (human avatar
OR animated OR voiced narrator) that any content-factory pipeline ever uses.

Layout on disk (default `/var/lib/content-factory/character_registry/`):

    registry.json                       — index: char_id → { name, type, tags, locked }
    <char_id>/canonical.json            — declared identity (HMAC-signed)
    <char_id>/face_embeddings.npz       — N reference face embeddings
    <char_id>/voice_embedding.npz       — speaker embedding (resemblyzer or MFCC fallback)
    <char_id>/outfits/<state>.json      — outfit state declarations + color histograms
    <char_id>/lock.json                 — HMAC-signed lock proof (canon_lock companion)
    <char_id>/aliases.json              — voice_id, lipsync_id, social_handle, render_seed, etc.

Per-run integration (every pipeline writes this BEFORE rendering):

    <run_path>/cast/cast_manifest.json
        {
          "version": "1.0",
          "scenes": [
            { "scene_id": "scene_01",
              "characters": [
                { "char_id": "quizzy",
                  "expected_outfit": "default",
                  "expected_state": "neutral",
                  "voice_id": "quizzy_v3",
                  "frame_share_min": 0.05
                }
              ]
            }
          ]
        }

G15 (character_identity gate) walks every shot, detects every face/character
region, matches each detected region against the cast manifest's declared
characters via embeddings, and blocks if:
  - any face cannot be matched to any declared character (ghost)
  - any declared character is undetected when frame_share_min > 0
  - any face matches the WRONG declared character (identity swap)
  - outfit/state histograms drift > threshold (continuity break)
  - voice embedding for spoken dialogue drifts from canonical (voice swap)

All operations sign their output with the same HMAC primitive as the studio gates.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Reuse the studio-gate HMAC primitive so every artifact is signed under one key.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio_gates"))
from __init__ import sign, verify, now_utc  # type: ignore  # noqa: E402,F401

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

# Two character TYPES, both supported uniformly through the same registry.
CHARACTER_TYPES = ("human_avatar", "animated_2d", "animated_3d", "voice_only", "mascot")


@dataclass
class OutfitState:
    state_id: str               # "default", "lab_coat", "halloween_2026"
    description: str
    primary_colors: list[str] = field(default_factory=list)  # canonical hex colors
    histogram: list[float] = field(default_factory=list)     # 12-bin HSV reference


@dataclass
class CharacterCanonical:
    char_id: str
    name: str
    char_type: str                            # one of CHARACTER_TYPES
    voice_id: str | None = None               # cross-ref into TTS/voice catalog
    aliases: list[str] = field(default_factory=list)
    outfit_states: list[OutfitState] = field(default_factory=list)
    appearance_notes: str = ""                # free-form for council
    locked: bool = False
    locked_by: str = ""
    locked_at: str = ""
    locked_until: str | None = None
    embedding_count: int = 0
    embedding_backend: str = "phash"          # insightface | face_recognition | phash
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "char_id":          self.char_id,
            "name":             self.name,
            "char_type":        self.char_type,
            "voice_id":         self.voice_id,
            "aliases":          self.aliases,
            "outfit_states":    [vars(o) for o in self.outfit_states],
            "appearance_notes": self.appearance_notes,
            "locked":           self.locked,
            "locked_by":        self.locked_by,
            "locked_at":        self.locked_at,
            "locked_until":     self.locked_until,
            "embedding_count":  self.embedding_count,
            "embedding_backend": self.embedding_backend,
            "signature":        self.signature,
        }
        return d


@dataclass
class CastMember:
    char_id: str
    expected_outfit: str = "default"
    expected_state: str = "neutral"
    voice_id: str | None = None
    frame_share_min: float = 0.0      # 0 = optional appearance, >0 = required


@dataclass
class CastScene:
    scene_id: str
    characters: list[CastMember] = field(default_factory=list)


@dataclass
class CastManifest:
    version: str = "1.0"
    scenes: list[CastScene] = field(default_factory=list)
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "scenes": [
                {
                    "scene_id": s.scene_id,
                    "characters": [vars(c) for c in s.characters],
                }
                for s in self.scenes
            ],
            "signature": self.signature,
        }


# ---------------------------------------------------------------------------
# Default registry root
# ---------------------------------------------------------------------------

def default_registry_root() -> Path:
    root = os.environ.get("CONTENTX_CHARACTER_REGISTRY")
    if root:
        return Path(root)
    return Path("/var/lib/content-factory/character_registry")


__all__ = [
    "CHARACTER_TYPES",
    "OutfitState", "CharacterCanonical", "CastMember", "CastScene", "CastManifest",
    "default_registry_root",
    "sign", "verify", "now_utc",
]
