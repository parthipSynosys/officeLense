"""Video validation and face extraction (OpenCV's bundled FFmpeg; no extra deps).

A video is indexed by sampling frames (VIDEO_SAMPLE_FPS, capped at
VIDEO_MAX_FRAMES), detecting + embedding every face, and merging repeated
sightings of the same person so one person walking through a 2-minute clip
doesn't produce 120 near-identical rows. Per person we keep up to
`MAX_SAMPLES_PER_PERSON` *diverse* embeddings (different angles/expressions),
which improves selfie recall compared to keeping a single one.

The frame with the most (best) faces becomes the poster: it is saved as the
row's full/thumb JPEGs, so covers, admin grids and guest results work unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.face.engine import DetectedFace, FaceEngine

# Cosine similarity above which two faces in the same video are the same person.
# (SFace's cross-photo match threshold is ~0.36; within one clip, same-person
# similarity is typically well above 0.6, different people well below 0.4.)
SAME_PERSON_SIM = 0.5
# A new sighting of a known person is kept as an extra sample only if it differs
# enough from that person's existing samples (otherwise it adds nothing).
DIVERSE_SAMPLE_SIM = 0.8
MAX_SAMPLES_PER_PERSON = 3
# Short clips are sampled up to this rate (still capped by VIDEO_MAX_FRAMES).
DENSE_SAMPLE_FPS = 5.0
# An upright detection this confident is never a rotated face: skip trying rotations.
CONFIDENT_UPRIGHT_SCORE = 0.92

# ISO-BMFF brands that are still images (HEIC/HEIF/AVIF), not videos.
_STILL_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"}
# Top-level QuickTime atoms that can start an old-style .mov without an ftyp box.
_QT_ATOMS = {b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}


class InvalidVideoError(ValueError):
    """Raised when content is not a decodable video."""


def sniff_video_type(head: bytes) -> str | None:
    """Identify a video container from its first bytes. Returns a file extension or None."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _STILL_BRANDS:
            return None
        return ".mov" if brand == b"qt  " else ".mp4"
    if len(head) >= 8 and head[4:8] in _QT_ATOMS:
        return ".mov"
    if head.startswith(b"\x1a\x45\xdf\xa3"):  # EBML: WebM / Matroska
        return ".webm" if b"webm" in head else ".mkv"
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"AVI ":
        return ".avi"
    return None


def read_head(path: Path, n: int = 64) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(n)


def _open(path: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise InvalidVideoError("Corrupt or unsupported video")
    return cap


def validate_video_file(path: Path) -> str:
    """Check the container and that at least one frame decodes. Returns the extension."""
    ext = sniff_video_type(read_head(path))
    if ext is None:
        raise InvalidVideoError("Unsupported or unrecognised video type")
    cap = _open(path)
    try:
        ok, frame = cap.read()
        if not ok or frame is None or frame.size == 0:
            raise InvalidVideoError("Video has no decodable frames")
    finally:
        cap.release()
    return ext


@dataclass
class VideoFace:
    embedding: np.ndarray
    face: DetectedFace
    t: float  # seconds into the video
    rotation: int = 0  # degrees clockwise applied to the frame before detection
    frame_w: int = 0  # size of the (rotated) frame the box refers to
    frame_h: int = 0


@dataclass
class _Person:
    samples: list[VideoFace] = field(default_factory=list)

    def best_similarity(self, emb: np.ndarray) -> float:
        return max(float(np.dot(s.embedding, emb)) for s in self.samples)


@dataclass
class VideoAnalysis:
    poster_rgb: Image.Image
    duration: float | None
    frames_sampled: int
    people: int
    faces: list[VideoFace]


_ROTATIONS: tuple[tuple[int, int | None], ...] = (
    (0, None),
    (180, cv2.ROTATE_180),
    (90, cv2.ROTATE_90_CLOCKWISE),
    (270, cv2.ROTATE_90_COUNTERCLOCKWISE),
)


def _orientation_quality(f: DetectedFace) -> float:
    """How convincingly a detection is an upright face.

    YuNet also fires on sideways/upside-down faces (with plausible-looking but
    wrong landmarks), and embeddings of those are garbage that never match the
    person. Correctly oriented faces score higher AND have their eyes spread
    wider relative to the box; both signals are combined.
    """
    eye_dx = abs(float(f.row[6] - f.row[4]))
    return f.score + 0.5 * (eye_dx / max(f.w, 1.0))


def detect_oriented(engine: FaceEngine, frame: np.ndarray) -> tuple[np.ndarray, list[DetectedFace], int]:
    """Detect faces in whichever 90° rotation of the frame shows them upright.

    Phone videos are often stored sideways, or flip mid-clip. Returns
    (rotated frame, faces in its coordinates, rotation in degrees clockwise).
    """
    best: tuple[float, np.ndarray, list[DetectedFace], int] | None = None
    for degrees, code in _ROTATIONS:
        img = frame if code is None else cv2.rotate(frame, code)
        faces = engine.detect(img)
        if not faces:
            continue
        quality = max(_orientation_quality(f) for f in faces)
        if best is None or quality > best[0]:
            best = (quality, img, faces, degrees)
        if degrees == 0 and max(f.score for f in faces) >= CONFIDENT_UPRIGHT_SCORE:
            break  # clearly upright already: skip the other three passes
    if best is None:
        return frame, [], 0
    return best[1], best[2], best[3]


def _is_blank(frame: np.ndarray) -> bool:
    """Black / nearly uniform frames (fade-ins, lens cap) make bad posters."""
    small = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
    return float(small.mean()) < 20 or float(small.std()) < 6


def analyze_video(path: Path, engine: FaceEngine, *, sample_fps: float, max_frames: int) -> VideoAnalysis:
    cap = _open(path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not (0 < fps < 1000):
            fps = 30.0  # unknown/garbage FPS: assume a typical rate
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if frame_count > 0 else None

        # Short clips are sampled densely (people may be on screen for <1 s);
        # long ones fall back to `sample_fps`, and never exceed `max_frames`.
        target_fps = sample_fps
        if duration:
            target_fps = min(max(sample_fps, max_frames / duration), max(sample_fps, DENSE_SAMPLE_FPS))
        stride = max(1, int(round(fps / target_fps)))
        if frame_count > 0 and frame_count / stride > max_frames:
            stride = int(np.ceil(frame_count / max_frames))

        people: list[_Person] = []
        poster: np.ndarray | None = None
        poster_key: tuple[int, float] = (-1, -1.0)
        fallback: np.ndarray | None = None
        frame_w = frame_h = 0
        idx = -1
        sampled = 0

        while sampled < max_frames:
            if not cap.grab():
                break
            idx += 1
            if idx % stride:
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None or frame.size == 0:
                continue
            sampled += 1
            t = idx / fps

            if fallback is None or (_is_blank(fallback) and not _is_blank(frame)):
                fallback = frame.copy()

            frame, detected, rotation = detect_oriented(engine, frame)
            if not detected:
                continue
            frame_h, frame_w = frame.shape[:2]
            key = (len(detected), sum(f.score for f in detected))
            if detected and key > poster_key:
                poster_key, poster = key, frame.copy()

            for f in detected:
                emb = engine.embed(frame, f)
                vf = VideoFace(embedding=emb, face=f, t=t, rotation=rotation, frame_w=frame_w, frame_h=frame_h)
                sims = [p.best_similarity(emb) for p in people]
                best = int(np.argmax(sims)) if sims else -1
                if best < 0 or sims[best] < SAME_PERSON_SIM:
                    people.append(_Person(samples=[vf]))
                    continue
                person = people[best]
                if sims[best] < DIVERSE_SAMPLE_SIM and len(person.samples) < MAX_SAMPLES_PER_PERSON:
                    person.samples.append(vf)
                else:
                    # Same look as an existing sample: keep whichever detection is stronger.
                    closest = max(range(len(person.samples)), key=lambda i: float(np.dot(person.samples[i].embedding, emb)))
                    if person.samples[closest].face.score < f.score:
                        person.samples[closest] = vf

        if sampled == 0:
            raise InvalidVideoError("Video has no decodable frames")
        if duration is None and idx >= 0:
            duration = (idx + 1) / fps

        chosen = poster if poster is not None else fallback
        assert chosen is not None
        return VideoAnalysis(
            poster_rgb=Image.fromarray(np.ascontiguousarray(chosen[:, :, ::-1])),
            duration=round(duration, 2) if duration else None,
            frames_sampled=sampled,
            people=len(people),
            faces=[s for p in people for s in p.samples],
        )
    finally:
        cap.release()
