"""Matching tests: similarity behaviour and result merging/sorting/pagination."""

from __future__ import annotations

import uuid
from datetime import date

from app.config import get_settings
from app.face.engine import SFACE_COSINE_THRESHOLD, cosine_similarity
from app.services.matching import MatchRow, build_response, merge_best, sort_matches
from tests.conftest import augment


def _emb(engine, img):
    return engine.embed(img, engine.detect(img)[0])


def test_default_threshold_is_sface_recommendation():
    assert get_settings().MATCH_THRESHOLD == SFACE_COSINE_THRESHOLD == 0.363


def test_same_person_scores_above_threshold(engine, faces_bgr):
    for name, img in faces_bgr.items():
        sim = cosine_similarity(_emb(engine, img), _emb(engine, augment(img)))
        assert sim >= SFACE_COSINE_THRESHOLD, f"{name}: same-person similarity {sim:.3f} too low"


def test_different_person_scores_below_threshold(engine, faces_bgr):
    a = _emb(engine, faces_bgr["astronaut"])
    b = _emb(engine, faces_bgr["lena"])
    assert cosine_similarity(a, b) < SFACE_COSINE_THRESHOLD


def test_pgvector_distance_convention():
    """`<=>` is cosine distance = 1 - similarity, so the SQL filter is d <= 1 - threshold."""
    threshold = 0.363
    for sim in (0.2, 0.363, 0.5, 0.9):
        assert ((1 - sim) <= (1 - threshold)) == (sim >= threshold)


def _row(event: str, d: date, sim: float, photo: uuid.UUID | None = None) -> MatchRow:
    eid = uuid.uuid5(uuid.NAMESPACE_DNS, event)
    return MatchRow(
        photo_id=photo or uuid.uuid4(),
        event_id=eid,
        event_name=event,
        event_type="Conference",
        event_date=d,
        thumb_path=f"{eid}/thumb/x.jpg",
        full_path=f"{eid}/full/x.jpg",
        width=1600,
        height=1067,
        similarity=sim,
    )


def test_merge_keeps_best_similarity_per_photo():
    pid = uuid.uuid4()
    s1 = [_row("A", date(2025, 1, 1), 0.40, pid)]
    s2 = [_row("A", date(2025, 1, 1), 0.71, pid), _row("A", date(2025, 1, 1), 0.50)]
    merged = merge_best([s1, s2])
    assert len(merged) == 2
    assert {r.photo_id: r.similarity for r in merged}[pid] == 0.71


def test_sort_by_event_date_then_similarity():
    rows = [
        _row("Old", date(2024, 5, 1), 0.9),
        _row("New", date(2025, 5, 1), 0.4),
        _row("New", date(2025, 5, 1), 0.8),
    ]
    ordered = sort_matches(rows)
    assert [(r.event_name, r.similarity) for r in ordered] == [("New", 0.8), ("New", 0.4), ("Old", 0.9)]


def test_build_response_pagination_and_by_event():
    rows = [_row("New", date(2025, 5, 1), 0.5 + i / 100) for i in range(5)] + [
        _row("Old", date(2024, 1, 1), 0.6) for _ in range(3)
    ]
    resp = build_response(rows, limit=3, offset=0)
    assert resp["total"] == 8
    assert [(e["name"], e["count"]) for e in resp["by_event"]] == [("New", 5), ("Old", 3)]
    assert len(resp["photos"]) == 3
    assert resp["photos"][0]["similarity"] == 0.54

    page3 = build_response(rows, limit=3, offset=6)
    assert len(page3["photos"]) == 2
    assert page3["offset"] == 6 and page3["limit"] == 3

    # Never leaks face data.
    assert set(resp["photos"][0]) == {
        "id", "event_id", "thumb_url", "full_url", "width", "height", "similarity",
        "media_type", "video_url", "duration", "match_time",
    }
    assert resp["photos"][0]["thumb_url"].startswith("/photos/")
