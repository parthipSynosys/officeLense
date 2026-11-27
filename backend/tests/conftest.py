"""Shared pytest fixtures.

* Engine / matching tests need the ONNX models: run `python scripts/download_models.py`.
* Sample face images are downloaded on first use into tests/.data/ (git-ignored):
    - astronaut.png — NASA portrait of Eileen Collins (public domain), via scikit-image
    - lena.jpg      — OpenCV sample image
* Database-backed API tests run only when TEST_DATABASE_URL points to a
  PostgreSQL 16 + pgvector database that may be wiped, e.g.
      TEST_DATABASE_URL=postgresql+psycopg://eventlens:eventlens@localhost:5432/eventlens_test
  They are skipped otherwise. They never use DATABASE_URL from your .env.
"""

from __future__ import annotations

import os
import tempfile
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / ".data"

# --- Environment must be set BEFORE the app is imported -----------------------
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["ADMIN_USERNAME"] = ""  # tests create their own admins
os.environ["ADMIN_PASSWORD"] = ""
os.environ["MODELS_DIR"] = str(BACKEND_DIR / "models")
os.environ["PHOTOS_DIR"] = tempfile.mkdtemp(prefix="eventlens-test-photos-")
os.environ["PUBLIC_PHOTOS_URL"] = "/photos"
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
# Never let tests touch a real database from .env: use the test DB or a dead one.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"

SAMPLE_IMAGES = {
    "astronaut.png": "https://raw.githubusercontent.com/scikit-image/scikit-image/v0.19.3/skimage/data/astronaut.png",
    "lena.jpg": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
}


def _models_present() -> bool:
    return (BACKEND_DIR / "models" / "face_detection_yunet_2023mar.onnx").is_file() and (
        BACKEND_DIR / "models" / "face_recognition_sface_2021dec.onnx"
    ).is_file()


@pytest.fixture(scope="session")
def engine():
    if not _models_present():
        pytest.skip("Face models missing — run `python scripts/download_models.py`")
    from app.face.engine import load_engine

    return load_engine()


@pytest.fixture(scope="session")
def sample_paths() -> dict[str, Path]:
    DATA_DIR.mkdir(exist_ok=True)
    out = {}
    for name, url in SAMPLE_IMAGES.items():
        dest = DATA_DIR / name
        if not dest.exists():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "eventlens-tests"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    dest.write_bytes(r.read())
            except Exception as exc:
                pytest.skip(f"Could not download sample image {name}: {exc}")
        out[name] = dest
    return out


@pytest.fixture(scope="session")
def faces_bgr(sample_paths):
    """Sample images decoded as BGR arrays: {'astronaut': ..., 'lena': ...}."""
    from app.services.images import load_image, pil_to_bgr

    return {p.stem: pil_to_bgr(load_image(p)) for p in sample_paths.values()}


def augment(img, *, flip=True, alpha=1.12, beta=8, angle=7.0, scale=0.88):
    """A different 'photo' of the same person: mirrored, re-lit, rotated, zoomed."""
    import cv2

    out = cv2.flip(img, 1) if flip else img.copy()
    out = cv2.convertScaleAbs(out, alpha=alpha, beta=beta)
    h, w = out.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    return cv2.warpAffine(out, m, (w, h), borderMode=cv2.BORDER_REFLECT)


def to_jpeg(img, quality: int = 92) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return buf.tobytes()


@pytest.fixture(scope="session")
def client(engine):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def client_no_models():
    """Client that works even if models are absent (auth tests)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


# --- Database ---------------------------------------------------------------


@pytest.fixture(scope="session")
def db_schema():
    if not TEST_DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to run database-backed tests")
    from sqlalchemy import text

    from app.db.session import engine as sa_engine
    from app.models import Base

    with sa_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(sa_engine)
    Base.metadata.create_all(sa_engine)
    yield sa_engine
    Base.metadata.drop_all(sa_engine)


@pytest.fixture
def db(db_schema):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with db_schema.begin() as conn:
        conn.execute(text("TRUNCATE faces, photos, events, admins RESTART IDENTITY CASCADE"))
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
