"""Face detection + recognition engine built on OpenCV Zoo models (Apache-2.0).

* Detection:   YuNet  (cv2.FaceDetectorYN)   face_detection_yunet_2023mar.onnx
* Recognition: SFace  (cv2.FaceRecognizerSF) face_recognition_sface_2021dec.onnx

This is the single reusable face module used by the API (selfie matching), the
RQ workers (photo indexing) and the bulk-index CLI. Models are loaded ONCE per
process via `load_engine()` / `get_engine()`.

All images passed in are OpenCV-style BGR uint8 numpy arrays (H, W, 3).
Embeddings are L2-normalised float32 vectors of length 128, so the cosine
similarity of two embeddings is simply their dot product.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# --- Detection parameters ---------------------------------------------------
DETECTION_MAX_SIDE = 1920  # longest side used for detection (boxes mapped back)
SCORE_THRESHOLD = 0.7
NMS_THRESHOLD = 0.3
TOP_K = 5000
MIN_FACE_PX = 40  # ignore faces smaller than this (in original-image pixels)

# --- Selfie quality parameters ------------------------------------------------
MIN_SELFIE_FACE_PX = 80
BLUR_NORMALISED_WIDTH = 160  # face crop is resized to this width before blur check

EMBEDDING_DIM = 128

# OpenCV's recommended cosine-similarity threshold for SFace.
SFACE_COSINE_THRESHOLD = 0.363


class SelfieError(str, Enum):
    """Machine-readable selfie rejection reasons (returned to the client)."""

    INVALID_IMAGE = "INVALID_IMAGE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    NO_FACE = "NO_FACE"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    FACE_TOO_SMALL = "FACE_TOO_SMALL"
    TOO_BLURRY = "TOO_BLURRY"
    TOO_DARK = "TOO_DARK"
    TOO_BRIGHT = "TOO_BRIGHT"


SELFIE_ERROR_MESSAGES: dict[SelfieError, str] = {
    SelfieError.INVALID_IMAGE: "This file isn't a supported image (JPEG, PNG, WebP or HEIC).",
    SelfieError.FILE_TOO_LARGE: "This image is too large. Please use a smaller photo.",
    SelfieError.NO_FACE: "We couldn't find a face. Face the camera in good light.",
    SelfieError.MULTIPLE_FACES: "More than one face was found. Please take a selfie of just you.",
    SelfieError.FACE_TOO_SMALL: "Your face is too small in the photo. Move closer to the camera.",
    SelfieError.TOO_BLURRY: "The selfie is too blurry. Hold still and try again.",
    SelfieError.TOO_DARK: "The selfie is too dark. Find better light and try again.",
    SelfieError.TOO_BRIGHT: "The selfie is too bright. Avoid direct light behind or on you.",
}


@dataclass(frozen=True)
class DetectedFace:
    """One detected face.

    `row` is YuNet's 15-value output mapped to ORIGINAL image coordinates:
    [x, y, w, h, re_x, re_y, le_x, le_y, nt_x, nt_y, rcm_x, rcm_y, lcm_x, lcm_y, score]
    """

    row: np.ndarray

    @property
    def x(self) -> float:
        return float(self.row[0])

    @property
    def y(self) -> float:
        return float(self.row[1])

    @property
    def w(self) -> float:
        return float(self.row[2])

    @property
    def h(self) -> float:
        return float(self.row[3])

    @property
    def score(self) -> float:
        return float(self.row[14])

    def box(self, scale: float = 1.0, clip_w: int | None = None, clip_h: int | None = None) -> dict:
        """Integer bounding box, optionally scaled and clipped to an image size."""
        x0, y0 = self.x * scale, self.y * scale
        x1, y1 = (self.x + self.w) * scale, (self.y + self.h) * scale
        if clip_w is not None:
            x0, x1 = max(0.0, x0), min(float(clip_w), x1)
        if clip_h is not None:
            y0, y1 = max(0.0, y0), min(float(clip_h), y1)
        return {
            "x": int(round(x0)),
            "y": int(round(y0)),
            "w": max(0, int(round(x1 - x0))),
            "h": max(0, int(round(y1 - y0))),
        }


@dataclass
class SelfieAnalysis:
    """Result of validating + embedding a selfie. Exactly one of error/embedding is set."""

    error: SelfieError | None
    embedding: np.ndarray | None = None
    face: DetectedFace | None = None
    metrics: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(v))
    if not np.isfinite(norm) or norm == 0.0:
        raise ValueError("Degenerate embedding (zero norm)")
    return v / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two embeddings (normalises defensively)."""
    return float(np.dot(l2_normalize(a), l2_normalize(b)))


class FaceEngine:
    """Wraps YuNet + SFace. Thread-safe (a lock guards the stateful OpenCV objects)."""

    def __init__(
        self,
        detector_path: str | Path,
        recognizer_path: str | Path,
        *,
        score_threshold: float = SCORE_THRESHOLD,
        nms_threshold: float = NMS_THRESHOLD,
        top_k: int = TOP_K,
    ) -> None:
        for p in (detector_path, recognizer_path):
            if not Path(p).is_file():
                raise FileNotFoundError(
                    f"Model file not found: {p}. Run `python scripts/download_models.py`."
                )
        # The initial input size is a placeholder; it is set per image in detect().
        self._detector = cv2.FaceDetectorYN.create(
            str(detector_path), "", (320, 320), score_threshold, nms_threshold, top_k
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        # FaceDetectorYN keeps the input size as state, and DNN nets are not
        # guaranteed thread-safe, so serialise access within a process.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ detect
    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        """Detect faces. Returns faces sorted by area (largest first).

        The image is downscaled so its longest side is at most 1920px for
        detection; boxes and landmarks are mapped back to original coordinates.
        Faces with a box side smaller than 40px are ignored.
        """
        if image is None or image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
            raise ValueError("detect() expects a non-empty BGR image of shape (H, W, 3)")

        h, w = image.shape[:2]
        scale = min(1.0, DETECTION_MAX_SIDE / float(max(h, w)))
        if scale < 1.0:
            det_w, det_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
            det_img = cv2.resize(image, (det_w, det_h), interpolation=cv2.INTER_AREA)
        else:
            det_img, det_w, det_h = image, w, h

        with self._lock:
            self._detector.setInputSize((det_w, det_h))
            _, raw = self._detector.detect(det_img)

        if raw is None or len(raw) == 0:
            return []

        faces: list[DetectedFace] = []
        for r in raw:
            row = np.asarray(r, dtype=np.float32).copy()
            row[:14] /= scale  # x, y, w, h and 5 landmark points back to original scale
            if row[2] < MIN_FACE_PX or row[3] < MIN_FACE_PX:
                continue
            faces.append(DetectedFace(row=row))
        faces.sort(key=lambda f: f.w * f.h, reverse=True)
        return faces

    # ------------------------------------------------------------------- embed
    def embed(self, image: np.ndarray, face: DetectedFace | np.ndarray) -> np.ndarray:
        """Align + crop the face with SFace and return an L2-normalised 128-d embedding.

        `face` must be in the coordinate space of `image` (use the same image you
        passed to detect(); detect() already maps rows back to original scale).
        """
        row = face.row if isinstance(face, DetectedFace) else np.asarray(face, dtype=np.float32)
        with self._lock:
            aligned = self._recognizer.alignCrop(image, row)
            feature = self._recognizer.feature(aligned)
        vec = l2_normalize(feature)
        if vec.shape[0] != EMBEDDING_DIM:
            raise ValueError(f"Unexpected embedding size {vec.shape[0]}")
        return vec

    # --------------------------------------------------------- selfie checks
    def analyze_selfie(
        self,
        image: np.ndarray,
        *,
        blur_threshold: float = 25.0,
        dark_threshold: float = 45.0,
        bright_threshold: float = 215.0,
        min_face_px: int = MIN_SELFIE_FACE_PX,
    ) -> SelfieAnalysis:
        """Validate a selfie and compute its embedding.

        Never raises for "bad selfie" conditions — returns an error code instead.
        """
        try:
            faces = self.detect(image)
        except ValueError:
            return SelfieAnalysis(error=SelfieError.INVALID_IMAGE)

        if not faces:
            # When no face is found, a very dark/bright frame is the likely cause.
            mean = float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean())
            if mean < dark_threshold * 0.9:
                return SelfieAnalysis(error=SelfieError.TOO_DARK, metrics={"brightness": mean})
            if mean > bright_threshold * 1.05:
                return SelfieAnalysis(error=SelfieError.TOO_BRIGHT, metrics={"brightness": mean})
            return SelfieAnalysis(error=SelfieError.NO_FACE)

        if len(faces) > 1:
            return SelfieAnalysis(error=SelfieError.MULTIPLE_FACES, metrics={"faces": len(faces)})

        face = faces[0]
        if min(face.w, face.h) < min_face_px:
            return SelfieAnalysis(
                error=SelfieError.FACE_TOO_SMALL, face=face, metrics={"face_px": min(face.w, face.h)}
            )

        crop = _face_crop_gray(image, face)
        brightness = float(crop.mean())
        sharpness = _sharpness(crop)
        metrics = {"brightness": brightness, "sharpness": sharpness, "face_px": min(face.w, face.h)}

        if brightness < dark_threshold:
            return SelfieAnalysis(error=SelfieError.TOO_DARK, face=face, metrics=metrics)
        if brightness > bright_threshold:
            return SelfieAnalysis(error=SelfieError.TOO_BRIGHT, face=face, metrics=metrics)
        if sharpness < blur_threshold:
            return SelfieAnalysis(error=SelfieError.TOO_BLURRY, face=face, metrics=metrics)

        try:
            embedding = self.embed(image, face)
        except (cv2.error, ValueError):
            return SelfieAnalysis(error=SelfieError.NO_FACE, metrics=metrics)
        return SelfieAnalysis(error=None, embedding=embedding, face=face, metrics=metrics)


def _face_crop_gray(image: np.ndarray, face: DetectedFace) -> np.ndarray:
    """Greyscale crop of the face box, clipped to the image."""
    h, w = image.shape[:2]
    x0, y0 = max(0, int(face.x)), max(0, int(face.y))
    x1, y1 = min(w, int(face.x + face.w)), min(h, int(face.y + face.h))
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        crop = image
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)


def _sharpness(gray_crop: np.ndarray) -> float:
    """Variance of the Laplacian on a face crop normalised to a fixed width,
    so the score doesn't depend on how large the face is in the frame."""
    ch, cw = gray_crop.shape[:2]
    if cw == 0 or ch == 0:
        return 0.0
    scale = BLUR_NORMALISED_WIDTH / float(cw)
    resized = cv2.resize(
        gray_crop,
        (BLUR_NORMALISED_WIDTH, max(1, int(round(ch * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )
    return float(cv2.Laplacian(resized, cv2.CV_64F).var())


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------
_engine: FaceEngine | None = None
_engine_lock = threading.Lock()


def load_engine(detector_path: str | Path | None = None, recognizer_path: str | Path | None = None) -> FaceEngine:
    """Load the models once for this process (idempotent)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            if detector_path is None or recognizer_path is None:
                from app.config import get_settings

                s = get_settings()
                detector_path = detector_path or s.yunet_path
                recognizer_path = recognizer_path or s.sface_path
            _engine = FaceEngine(detector_path, recognizer_path)
            log.info("Face models loaded (YuNet + SFace)")
        return _engine


def get_engine() -> FaceEngine:
    """Return the loaded engine, loading it on first use."""
    return _engine if _engine is not None else load_engine()


def engine_loaded() -> bool:
    return _engine is not None
