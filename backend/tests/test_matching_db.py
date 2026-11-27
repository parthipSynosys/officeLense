"""Database tests for the matching rules: quality gating, query expansion, video match time.

Uses synthetic unit vectors so every similarity is known exactly.
"""

from __future__ import annotations

import uuid
from datetime import date

import numpy as np
import pytest

from app.models import Event, Face, Photo
from app.services.matching import count_pending, find_matches

THRESHOLD = 0.363
GOOD_BOX = {"x": 0, "y": 0, "w": 120, "h": 120}


def _vec(**coeffs: float) -> list[float]:
    """Unit vector from basis coefficients, e.g. _vec(e0=0.4, e4=0.9165)."""
    v = np.zeros(128, dtype=np.float32)
    for k, c in coeffs.items():
        v[int(k[1:])] = c
    return (v / np.linalg.norm(v)).tolist()


SELFIE = np.asarray(_vec(e0=1.0), dtype=np.float32)


@pytest.fixture
def scene(db):
    event = Event(name="Annual Day", type="Cultural", event_date=date(2025, 6, 1), is_published=True)
    db.add(event)
    db.flush()

    def add(name: str, embedding, *, score=0.95, box=None, status="done", media="photo"):
        p = Photo(
            event_id=event.id,
            original_filename=f"{name}.jpg",
            file_hash=uuid.uuid4().hex,
            full_path=f"{event.id}/full/{name}.jpg",
            thumb_path=f"{event.id}/thumb/{name}.jpg",
            media_type=media,
            video_path=f"{event.id}/video/{name}.mp4" if media == "video" else None,
            width=1600,
            height=1200,
            face_count=1,
            status=status,
        )
        db.add(p)
        db.flush()
        if embedding is not None:
            db.add(Face(photo_id=p.id, event_id=event.id, embedding=embedding, box=box or GOOD_BOX, score=score))
        return p.id

    ids = {
        # Clean face just above the threshold: matches.
        "good": add("good", _vec(e0=0.40, e4=0.9165)),
        # Same similarity but a weak (blurry/side-on) detection: rejected.
        "weak": add("weak", _vec(e0=0.40, e5=0.9165), score=0.75),
        # Weak detection but a clearly strong similarity: still matches.
        "weak_strong": add("weak_strong", _vec(e0=0.45, e6=0.893), score=0.75),
        # Tiny face just above the threshold: rejected.
        "tiny": add("tiny", _vec(e0=0.40, e8=0.9165), box={"x": 0, "y": 0, "w": 20, "h": 20}),
        # Certain match -> becomes an expansion seed.
        "seed": add("seed", _vec(e0=0.80, e1=0.60)),
        # Under the selfie threshold (0.32) but very close to the seed: found by expansion.
        "expanded": add("expanded", _vec(e0=0.32, e1=0.70, e2=0.638)),
        # Close to the seed but far from the selfie (0.20): never matched.
        "drift": add("drift", _vec(e0=0.20, e1=0.80, e3=0.566)),
        # Video where the guest is seen at 12.5 s.
        "video": add("video", _vec(e0=0.60, e7=0.80), box={**GOOD_BOX, "t": 12.5}, media="video"),
        # Still being indexed: not matchable yet, but counted as pending.
        "queued": add("queued", None, status="queued"),
    }
    db.commit()
    return ids


def _matched(db, **kw) -> dict[uuid.UUID, object]:
    return {r.photo_id: r for r in find_matches(db, [SELFIE], threshold=THRESHOLD, **kw)}


def test_quality_gating(db, scene):
    got = _matched(db)
    assert scene["good"] in got
    assert scene["weak_strong"] in got
    assert scene["weak"] not in got
    assert scene["tiny"] not in got


def test_query_expansion_finds_more_without_drifting(db, scene):
    assert scene["expanded"] not in _matched(db, expand=False)
    got = _matched(db)
    assert scene["expanded"] in got
    assert got[scene["expanded"]].similarity == pytest.approx(0.32, abs=1e-3)  # honest selfie similarity
    assert scene["drift"] not in got


def test_video_match_time(db, scene):
    got = _matched(db)
    assert got[scene["video"]].match_time == pytest.approx(12.5)
    assert got[scene["good"]].match_time is None


def test_pending_count(db, scene):
    assert count_pending(db) == 1
