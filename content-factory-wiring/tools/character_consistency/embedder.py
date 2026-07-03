"""Multi-modal character embedders: face, voice, outfit.

Single interface, multiple backends. Each function returns a numpy embedding
plus a `backend` string so consumers know what they got. All backends are
optional — if none installed, the implementation falls back to perceptual
hashing (face), MFCC (voice), or HSV histogram (outfit).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Face embeddings
# ---------------------------------------------------------------------------

_FACE_BACKEND: str | None = None
_FACE_MODEL = None


def face_backend() -> str:
    global _FACE_BACKEND, _FACE_MODEL
    if _FACE_BACKEND is not None:
        return _FACE_BACKEND
    try:
        from insightface.app import FaceAnalysis  # type: ignore
        _FACE_MODEL = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _FACE_MODEL.prepare(ctx_id=-1, det_size=(320, 320))
        _FACE_BACKEND = "insightface"
        return _FACE_BACKEND
    except Exception:
        pass
    try:
        import face_recognition  # type: ignore
        _FACE_MODEL = face_recognition
        _FACE_BACKEND = "face_recognition"
        return _FACE_BACKEND
    except Exception:
        pass
    _FACE_BACKEND = "phash"
    return _FACE_BACKEND


def detect_and_embed_faces(rgb_image: np.ndarray) -> list[dict[str, Any]]:
    """Detect all faces in `rgb_image` and embed each. Returns a list of dicts:
        [{ "bbox": (x1,y1,x2,y2), "embedding": np.ndarray, "backend": str }, ...]
    Sorted by area, largest first.
    """
    backend = face_backend()
    if backend == "insightface":
        bgr = rgb_image[..., ::-1]
        faces = _FACE_MODEL.get(bgr)
        out = []
        for f in faces:
            x1, y1, x2, y2 = (int(v) for v in f.bbox)
            out.append({
                "bbox": (x1, y1, x2, y2),
                "embedding": f.embedding.astype(np.float32),
                "backend": backend,
                "confidence": float(getattr(f, "det_score", 1.0)),
            })
        out.sort(key=lambda d: (d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1]),
                 reverse=True)
        return out

    if backend == "face_recognition":
        locations = _FACE_MODEL.face_locations(rgb_image.astype(np.uint8))
        encodings = _FACE_MODEL.face_encodings(rgb_image.astype(np.uint8), locations, num_jitters=1)
        out = []
        for (top, right, bottom, left), enc in zip(locations, encodings):
            out.append({
                "bbox": (int(left), int(top), int(right), int(bottom)),
                "embedding": enc.astype(np.float32),
                "backend": backend,
                "confidence": 1.0,
            })
        out.sort(key=lambda d: (d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1]),
                 reverse=True)
        return out

    # phash fallback: treat the whole frame as one synthetic face region.
    from PIL import Image
    h, w = rgb_image.shape[:2]
    cx, cy = w // 2, h // 2
    rw, rh = int(w * 0.4), int(h * 0.4)
    bbox = (cx - rw // 2, cy - rh // 2, cx + rw // 2, cy + rh // 2)
    crop = rgb_image[bbox[1]:bbox[3], bbox[0]:bbox[2]]
    if crop.size == 0:
        return []
    img = Image.fromarray(crop.astype(np.uint8)).convert("L").resize((8, 8))
    pixels = np.array(img, dtype=np.float32)
    bits = (pixels > pixels.mean()).astype(np.float32).flatten()
    return [{"bbox": bbox, "embedding": bits, "backend": "phash", "confidence": 0.5}]


def face_distance(a: np.ndarray, b: np.ndarray, backend: str) -> float:
    """Return [0, 1] distance regardless of backend."""
    if backend == "phash":
        if len(a) != len(b): return 1.0
        return float(np.mean(a != b))
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 1.0
    cos = float(np.dot(a, b) / (na * nb))
    return max(0.0, min(1.0, (1.0 - cos) / 2.0))


def face_distance_to_bank(emb: np.ndarray, bank: np.ndarray, backend: str) -> float:
    """Distance to the closest entry in a face bank (canonical reference set)."""
    if bank is None or len(bank) == 0:
        return 1.0
    distances = [face_distance(emb, ref, backend) for ref in bank]
    return min(distances)


# Per-backend default thresholds — calibrated against LFW-style validation pairs.
FACE_THRESHOLD = {
    "insightface":      0.20,   # >0.20 = different identity
    "face_recognition": 0.28,
    "phash":            0.39,
}


# ---------------------------------------------------------------------------
# Outfit / state — HSV histogram on torso region (below face bbox)
# ---------------------------------------------------------------------------

def outfit_histogram(rgb_image: np.ndarray, face_bbox: tuple[int, int, int, int]) -> np.ndarray:
    """12-bin HSV histogram of the estimated torso region (below the face)."""
    x1, y1, x2, y2 = face_bbox
    h, w = rgb_image.shape[:2]
    face_h = y2 - y1
    face_w = x2 - x1
    # Torso = below the face, roughly 1.5x face height, 2x face width, centered horizontally.
    tx1 = max(0, x1 - face_w // 2)
    tx2 = min(w, x2 + face_w // 2)
    ty1 = min(h - 1, y2)
    ty2 = min(h, y2 + int(face_h * 1.5))
    if ty2 <= ty1 + 2 or tx2 <= tx1 + 2:
        return np.zeros(12, dtype=np.float32)
    torso = rgb_image[ty1:ty2, tx1:tx2]
    # RGB → HSV (simple)
    rgb = torso.astype(np.float32) / 255.0
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    delta = mx - mn + 1e-6
    h_chan = np.zeros_like(mx)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask_r = (mx == r)
    mask_g = (mx == g) & ~mask_r
    mask_b = (mx == b) & ~mask_r & ~mask_g
    h_chan = np.where(mask_r, ((g - b) / delta) % 6, h_chan)
    h_chan = np.where(mask_g, ((b - r) / delta) + 2, h_chan)
    h_chan = np.where(mask_b, ((r - g) / delta) + 4, h_chan)
    h_chan = (h_chan / 6.0)  # [0, 1)
    hist, _ = np.histogram(h_chan, bins=12, range=(0.0, 1.0))
    return (hist / hist.sum() if hist.sum() > 0 else hist).astype(np.float32)


def outfit_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Chi-square distance between two histograms, normalized to [0, 1]."""
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    eps = 1e-6
    chi2 = 0.5 * np.sum((a - b) ** 2 / (a + b + eps))
    return float(min(1.0, chi2))


# ---------------------------------------------------------------------------
# Voice — speaker embedding for dialogue continuity
# ---------------------------------------------------------------------------

_VOICE_BACKEND: str | None = None
_VOICE_ENCODER = None


def voice_backend() -> str:
    global _VOICE_BACKEND, _VOICE_ENCODER
    if _VOICE_BACKEND is not None:
        return _VOICE_BACKEND
    try:
        from resemblyzer import VoiceEncoder  # type: ignore
        _VOICE_ENCODER = VoiceEncoder("cpu")
        _VOICE_BACKEND = "resemblyzer"
        return _VOICE_BACKEND
    except Exception:
        pass
    _VOICE_BACKEND = "mfcc"
    return _VOICE_BACKEND


def voice_embed(audio_path: Path) -> tuple[str, np.ndarray | None]:
    backend = voice_backend()
    if backend == "resemblyzer":
        try:
            from resemblyzer import preprocess_wav  # type: ignore
            wav = preprocess_wav(audio_path)
            return backend, _VOICE_ENCODER.embed_utterance(wav).astype(np.float32)
        except Exception:
            return backend, None
    try:
        import wave
        with wave.open(str(audio_path), "rb") as w:
            sr = w.getframerate()
            n = w.getnframes()
            frames = w.readframes(min(n, sr * 5))
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size < 1024:
            return backend, None
        # 13-bin MFCC-lite: log-magnitude of 13-band Mel filterbank means
        spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
        bands = np.array_split(spectrum, 13)
        emb = np.array([np.log1p(b.mean()) for b in bands], dtype=np.float32)
        emb /= max(np.linalg.norm(emb), 1e-6)
        return backend, emb
    except Exception:
        return backend, None


def voice_distance(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 1.0
    cos = float(np.dot(a, b) / (na * nb))
    return max(0.0, min(1.0, (1.0 - cos) / 2.0))


VOICE_THRESHOLD = {
    "resemblyzer": 0.30,
    "mfcc":        0.45,
}
