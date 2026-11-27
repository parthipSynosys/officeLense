"""Face engine tests: detection, selfie quality checks, embeddings."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.face.engine import EMBEDDING_DIM, SelfieError


def test_detects_face_in_sample_image(engine, faces_bgr):
    for name, img in faces_bgr.items():
        faces = engine.detect(img)
        assert len(faces) == 1, f"expected exactly one face in {name}"
        f = faces[0]
        assert f.score >= 0.7
        assert f.w >= 40 and f.h >= 40


def test_detect_maps_boxes_back_after_downscale(engine, faces_bgr):
    """A huge image is downscaled to 1920px for detection; boxes must be in original pixels."""
    img = faces_bgr["lena"]
    small = engine.detect(img)[0]
    big_img = cv2.resize(img, (img.shape[1] * 5, img.shape[0] * 5), interpolation=cv2.INTER_LINEAR)
    big = engine.detect(big_img)
    assert big, "face should still be found in the upscaled image"
    f = big[0]
    assert f.w == pytest.approx(small.w * 5, rel=0.15)
    assert f.x == pytest.approx(small.x * 5, rel=0.15, abs=25)


def test_valid_selfie_accepted(engine, faces_bgr):
    result = engine.analyze_selfie(faces_bgr["lena"])
    assert result.ok, result.error
    assert result.embedding is not None


def test_rejects_no_face(engine):
    noise = np.random.default_rng(0).integers(0, 255, (600, 600, 3), dtype=np.uint8)
    assert engine.analyze_selfie(noise).error == SelfieError.NO_FACE
    grey = np.full((600, 600, 3), 128, dtype=np.uint8)
    assert engine.analyze_selfie(grey).error == SelfieError.NO_FACE


def test_rejects_multiple_faces(engine, faces_bgr):
    a = cv2.resize(faces_bgr["astronaut"], (512, 512))
    b = cv2.resize(faces_bgr["lena"], (512, 512))
    assert engine.analyze_selfie(np.hstack([a, b])).error == SelfieError.MULTIPLE_FACES


def test_rejects_small_face(engine, faces_bgr):
    small = cv2.resize(faces_bgr["lena"], (200, 200), interpolation=cv2.INTER_AREA)
    assert engine.analyze_selfie(small).error == SelfieError.FACE_TOO_SMALL


def test_rejects_blurry(engine, faces_bgr):
    blurry = cv2.GaussianBlur(faces_bgr["lena"], (0, 0), 3)
    assert engine.analyze_selfie(blurry).error == SelfieError.TOO_BLURRY


def test_rejects_dark_and_bright(engine, faces_bgr):
    dark = cv2.convertScaleAbs(faces_bgr["lena"], alpha=0.15)
    assert engine.analyze_selfie(dark).error == SelfieError.TOO_DARK
    bright = cv2.convertScaleAbs(faces_bgr["lena"], alpha=0.3, beta=200)
    assert engine.analyze_selfie(bright).error == SelfieError.TOO_BRIGHT


def test_embedding_is_128d_and_normalized(engine, faces_bgr):
    img = faces_bgr["astronaut"]
    emb = engine.embed(img, engine.detect(img)[0])
    assert emb.shape == (EMBEDDING_DIM,)
    assert emb.dtype == np.float32
    assert np.linalg.norm(emb) == pytest.approx(1.0, abs=1e-5)
    assert np.all(np.isfinite(emb))


def test_detect_rejects_invalid_input(engine):
    with pytest.raises(ValueError):
        engine.detect(np.zeros((10, 10), dtype=np.uint8))
