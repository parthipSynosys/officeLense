"""Video support: container sniffing, validation, frame sampling + face merging."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.indexing import UnsupportedMediaError, detect_media
from app.services.videos import (
    InvalidVideoError,
    analyze_video,
    sniff_video_type,
    validate_video_file,
)


def _write_video(path: Path, frames: list[np.ndarray], fps: float = 10.0) -> Path:
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert writer.isOpened(), "OpenCV build cannot write mp4v"
    for f in frames:
        writer.write(f)
    writer.release()
    return path


def _canvas(face: np.ndarray | None, w: int = 960, h: int = 540, x: int = 0) -> np.ndarray:
    img = np.full((h, w, 3), 90, dtype=np.uint8)
    if face is not None:
        f = cv2.resize(face, (h, h))
        img[:, x : x + h] = f
    return img


def test_sniff_video_types():
    assert sniff_video_type(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8) == ".mp4"
    assert sniff_video_type(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 8) == ".mov"
    assert sniff_video_type(b"\x00\x00\x00\x08wide" + b"\x00" * 8) == ".mov"
    assert sniff_video_type(b"\x1a\x45\xdf\xa3\x01\x00webm") == ".webm"
    assert sniff_video_type(b"RIFF\x00\x00\x00\x00AVI LIST") == ".avi"
    # HEIC / AVIF stills use the same box format but are not videos.
    assert sniff_video_type(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8) is None
    assert sniff_video_type(b"\x00\x00\x00\x18ftypavif" + b"\x00" * 8) is None
    assert sniff_video_type(b"\xff\xd8\xff\xe0") is None


def test_validate_rejects_fake_video(tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"garbage" * 100)
    with pytest.raises(InvalidVideoError):
        validate_video_file(fake)
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"hello world" * 10)
    with pytest.raises(UnsupportedMediaError):
        detect_media(junk)


def test_detect_media_recognises_video(tmp_path, faces_bgr):
    path = _write_video(tmp_path / "clip.mp4", [_canvas(faces_bgr["lena"])] * 5)
    assert detect_media(path) == ("video", ".mp4")


def test_same_person_across_frames_is_merged(tmp_path, engine, faces_bgr):
    """One person in 4 s of video (+ a blank intro) -> one person, poster has the face."""
    lena = faces_bgr["lena"]
    frames = [_canvas(None)] * 10 + [_canvas(lena, x=20 + i * 8) for i in range(40)]
    path = _write_video(tmp_path / "one.mp4", frames, fps=10)

    result = analyze_video(path, engine, sample_fps=2, max_frames=100)
    assert result.people == 1
    assert 1 <= len(result.faces) <= 3
    assert result.duration == pytest.approx(5.0, abs=0.3)
    assert result.frames_sampled == pytest.approx(25, abs=1)  # short clip -> dense 5 fps
    assert all(vf.t >= 1.0 for vf in result.faces)  # never seen in the blank intro
    # The poster must be a frame that contains the face.
    poster = cv2.cvtColor(np.asarray(result.poster_rgb), cv2.COLOR_RGB2BGR)
    assert len(engine.detect(poster)) == 1


def test_two_people_stay_separate(tmp_path, engine, faces_bgr):
    a = _canvas(faces_bgr["lena"])
    b = _canvas(faces_bgr["astronaut"])
    path = _write_video(tmp_path / "two.mp4", [a] * 20 + [b] * 20, fps=10)
    result = analyze_video(path, engine, sample_fps=2, max_frames=100)
    assert result.people == 2


def test_max_frames_caps_sampling(tmp_path, engine, faces_bgr):
    path = _write_video(tmp_path / "long.mp4", [_canvas(faces_bgr["lena"])] * 60, fps=10)
    result = analyze_video(path, engine, sample_fps=10, max_frames=5)
    assert result.frames_sampled <= 5


@pytest.mark.parametrize("rotate", [cv2.ROTATE_180, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE])
def test_rotated_faces_are_found_upright(tmp_path, engine, faces_bgr, rotate):
    """Phone clips are often stored sideways/upside down: the embedding must still match."""
    lena = faces_bgr["lena"]
    reference = engine.embed(lena, engine.detect(lena)[0])
    frame = cv2.rotate(_canvas(lena, w=720, h=720), rotate)
    path = _write_video(tmp_path / "rotated.mp4", [frame] * 20, fps=10)

    result = analyze_video(path, engine, sample_fps=2, max_frames=100)
    assert result.people == 1
    assert max(float(np.dot(vf.embedding, reference)) for vf in result.faces) >= 0.6
    assert all(vf.rotation != 0 for vf in result.faces)
    poster = cv2.cvtColor(np.asarray(result.poster_rgb), cv2.COLOR_RGB2BGR)
    assert engine.detect(poster)[0].score >= 0.8  # poster is saved upright


def test_upright_faces_skip_rotation(tmp_path, engine, faces_bgr):
    path = _write_video(tmp_path / "upright.mp4", [_canvas(faces_bgr["lena"])] * 10, fps=10)
    result = analyze_video(path, engine, sample_fps=2, max_frames=100)
    assert {vf.rotation for vf in result.faces} == {0}
