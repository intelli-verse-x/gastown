"""CharacterRegistry — CRUD on the on-disk character registry.

Operations:
    create_character()   — new character, writes canonical.json + index entry
    get_character()      — load canonical.json + verify signature
    add_face_reference() — append face embedding to face_embeddings.npz
    add_voice_reference()— write voice_embedding.npz
    lock(), unlock()     — controlled mutation
    list_characters()    — filter by tag / type
    canonical_face_bank()— return all N face embeddings as np.ndarray

Every mutation appends to a registry-level chain_of_custody.jsonl so we can
audit "who locked Quizzy at what time, who unlocked, who added a new reference".
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _models import (   # type: ignore  # noqa: E402
    CHARACTER_TYPES,
    CharacterCanonical,
    OutfitState,
    sign,
    verify,
    now_utc,
    default_registry_root,
)


class RegistryError(Exception):
    pass


class CharacterRegistry:
    def __init__(self, root: Path | None = None):
        self.root = root or default_registry_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "registry.json"
        self.coc_path = self.root / "chain_of_custody.jsonl"

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------
    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text())
        except json.JSONDecodeError:
            return {}

    def _save_index(self, idx: dict[str, dict[str, Any]]) -> None:
        self.index_path.write_text(json.dumps(idx, indent=2, sort_keys=True))

    def _coc(self, event: str, char_id: str, extra: dict[str, Any] | None = None) -> None:
        entry = {
            "kind": event,
            "char_id": char_id,
            "at": now_utc(),
            "extra": extra or {},
        }
        entry["signature"] = sign(entry)
        with self.coc_path.open("a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def list_characters(self, char_type: str | None = None, tag: str | None = None) -> list[str]:
        idx = self._load_index()
        out = []
        for cid, meta in idx.items():
            if char_type and meta.get("char_type") != char_type:
                continue
            if tag and tag not in meta.get("tags", []):
                continue
            out.append(cid)
        return sorted(out)

    def create_character(
        self,
        char_id: str,
        name: str,
        char_type: str,
        voice_id: str | None = None,
        tags: list[str] | None = None,
        outfit_states: list[OutfitState] | None = None,
        appearance_notes: str = "",
    ) -> CharacterCanonical:
        if char_type not in CHARACTER_TYPES:
            raise RegistryError(f"char_type must be one of {CHARACTER_TYPES}")
        char_dir = self.root / char_id
        if char_dir.exists():
            raise RegistryError(f"character '{char_id}' already exists")

        char_dir.mkdir(parents=True)
        (char_dir / "outfits").mkdir()

        canon = CharacterCanonical(
            char_id=char_id,
            name=name,
            char_type=char_type,
            voice_id=voice_id,
            outfit_states=outfit_states or [OutfitState(state_id="default", description=name)],
            appearance_notes=appearance_notes,
        )
        body = canon.to_dict()
        body.pop("signature", None)
        canon.signature = sign(body)
        (char_dir / "canonical.json").write_text(json.dumps(canon.to_dict(), indent=2))

        idx = self._load_index()
        idx[char_id] = {
            "name": name,
            "char_type": char_type,
            "voice_id": voice_id,
            "tags": tags or [],
            "locked": False,
            "embedding_count": 0,
            "created_at": now_utc(),
        }
        self._save_index(idx)
        self._coc("character_created", char_id, {"name": name, "char_type": char_type})
        return canon

    def get_character(self, char_id: str) -> CharacterCanonical | None:
        canon_path = self.root / char_id / "canonical.json"
        if not canon_path.exists():
            return None
        data = json.loads(canon_path.read_text())
        if not verify(data):
            raise RegistryError(f"canonical signature invalid for {char_id}")
        outfits = [OutfitState(**o) for o in data.get("outfit_states", [])]
        data["outfit_states"] = outfits
        return CharacterCanonical(**data)

    def exists(self, char_id: str) -> bool:
        return (self.root / char_id / "canonical.json").exists()

    # ------------------------------------------------------------------
    # Lock / unlock
    # ------------------------------------------------------------------
    def lock(self, char_id: str, locked_by: str, duration_hours: int = 24 * 30) -> None:
        canon = self.get_character(char_id)
        if canon is None:
            raise RegistryError(f"unknown character {char_id}")
        canon.locked = True
        canon.locked_by = locked_by
        canon.locked_at = now_utc()
        canon.locked_until = (datetime.now(timezone.utc) + timedelta(hours=duration_hours)).isoformat()
        body = canon.to_dict()
        body.pop("signature", None)
        canon.signature = sign(body)
        (self.root / char_id / "canonical.json").write_text(json.dumps(canon.to_dict(), indent=2))
        idx = self._load_index()
        idx[char_id]["locked"] = True
        self._save_index(idx)
        self._coc("character_locked", char_id, {"by": locked_by, "until": canon.locked_until})

    def unlock(self, char_id: str, unlocked_by: str, reason: str) -> None:
        canon = self.get_character(char_id)
        if canon is None:
            raise RegistryError(f"unknown character {char_id}")
        canon.locked = False
        canon.locked_until = None
        body = canon.to_dict()
        body.pop("signature", None)
        canon.signature = sign(body)
        (self.root / char_id / "canonical.json").write_text(json.dumps(canon.to_dict(), indent=2))
        idx = self._load_index()
        idx[char_id]["locked"] = False
        self._save_index(idx)
        self._coc("character_unlocked", char_id, {"by": unlocked_by, "reason": reason})

    # ------------------------------------------------------------------
    # Embeddings — face bank + voice
    # ------------------------------------------------------------------
    def add_face_reference(self, char_id: str, embedding: np.ndarray, backend: str, source: str) -> None:
        char_dir = self.root / char_id
        if not char_dir.exists():
            raise RegistryError(f"unknown character {char_id}")
        face_path = char_dir / "face_embeddings.npz"
        if face_path.exists():
            existing = np.load(face_path)
            arr = existing["arr"]
            backends = list(existing.get("backends", [backend] * len(arr)))
            sources = list(existing.get("sources", [""] * len(arr)))
            if arr.shape[1] != len(embedding):
                raise RegistryError(
                    f"embedding dim mismatch: existing={arr.shape[1]} new={len(embedding)}"
                )
            arr = np.vstack([arr, embedding.reshape(1, -1).astype(np.float32)])
        else:
            arr = embedding.reshape(1, -1).astype(np.float32)
            backends, sources = [], []
        backends.append(backend)
        sources.append(source)
        np.savez(face_path, arr=arr, backends=np.array(backends), sources=np.array(sources))

        canon = self.get_character(char_id)
        if canon:
            canon.embedding_count = arr.shape[0]
            canon.embedding_backend = backend
            body = canon.to_dict()
            body.pop("signature", None)
            canon.signature = sign(body)
            (char_dir / "canonical.json").write_text(json.dumps(canon.to_dict(), indent=2))

        idx = self._load_index()
        if char_id in idx:
            idx[char_id]["embedding_count"] = arr.shape[0]
            self._save_index(idx)
        self._coc("face_reference_added", char_id, {"backend": backend, "source": source})

    def add_voice_reference(self, char_id: str, embedding: np.ndarray, backend: str, source: str) -> None:
        char_dir = self.root / char_id
        if not char_dir.exists():
            raise RegistryError(f"unknown character {char_id}")
        np.savez(
            char_dir / "voice_embedding.npz",
            arr=embedding.reshape(1, -1).astype(np.float32),
            backend=np.array([backend]),
            source=np.array([source]),
        )
        self._coc("voice_reference_added", char_id, {"backend": backend, "source": source})

    def face_bank(self, char_id: str) -> np.ndarray | None:
        face_path = self.root / char_id / "face_embeddings.npz"
        if not face_path.exists(): return None
        try:
            data = np.load(face_path)
            return data["arr"]
        except Exception:
            return None

    def voice_reference(self, char_id: str) -> np.ndarray | None:
        vp = self.root / char_id / "voice_embedding.npz"
        if not vp.exists(): return None
        try:
            return np.load(vp)["arr"][0]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Cast manifest helpers
    # ------------------------------------------------------------------
    def validate_cast_manifest(self, manifest: dict[str, Any]) -> list[str]:
        """Return list of validation errors; empty = valid."""
        errors = []
        idx = self._load_index()
        for scene in manifest.get("scenes", []):
            for ch in scene.get("characters", []):
                cid = ch.get("char_id")
                if not cid or cid not in idx:
                    errors.append(
                        f"scene {scene.get('scene_id')}: char_id '{cid}' not in registry"
                    )
        return errors
