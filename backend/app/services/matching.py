"""Selfie -> photo matching.

Search strategy (correctness first)
-----------------------------------
For every request we run ONE exact (non-approximate) scan over `faces`,
restricted to published events and to any event / type filters:

    SELECT photo_id, MIN(LEAST(emb <=> q1, emb <=> q2, ...)) AS d
    FROM faces JOIN events ...
    WHERE events.is_published AND <filters>
      AND LEAST(...) <= 1 - threshold
    GROUP BY photo_id

`<=>` is pgvector's cosine DISTANCE (1 - similarity), so "similarity >=
threshold" becomes "distance <= 1 - threshold". Because the query has no
`ORDER BY distance LIMIT k`, PostgreSQL never uses the HNSW index here: it is
an exact sequential (parallel) scan, so filtered results are always complete
(an approximate index scan + filter can silently drop matches). With 128-d
vectors, ~100k faces scan well under 1 second; see scripts/benchmark_match.py.

Using LEAST() across all selfie embeddings and MIN() per photo implements the
merge rule "per photo keep the BEST similarity across all selfies".
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Event, Face, Photo
from app.services import storage


@dataclass(frozen=True)
class MatchRow:
    photo_id: uuid.UUID
    event_id: uuid.UUID
    event_name: str
    event_type: str
    event_date: date
    thumb_path: str | None
    full_path: str | None
    width: int | None
    height: int | None
    similarity: float
    media_type: str = "photo"
    video_path: str | None = None
    duration: float | None = None


def find_matches(
    db: Session,
    embeddings: Sequence[np.ndarray],
    *,
    threshold: float,
    event_ids: Sequence[uuid.UUID] | None = None,
    event_types: Sequence[str] | None = None,
) -> list[MatchRow]:
    """Return every matching photo (best similarity per photo), unsorted."""
    if not embeddings:
        return []
    max_distance = 1.0 - float(threshold)

    distances = [Face.embedding.cosine_distance(np.asarray(e, dtype=np.float32).tolist()) for e in embeddings]
    dist = distances[0] if len(distances) == 1 else func.least(*distances)

    best = (
        select(Face.photo_id.label("photo_id"), func.min(dist).label("d"))
        .join(Event, Event.id == Face.event_id)
        .where(Event.is_published.is_(True))
        .where(dist <= max_distance)
        .group_by(Face.photo_id)
    )
    if event_ids:
        best = best.where(Face.event_id.in_(list(event_ids)))
    if event_types:
        best = best.where(Event.type.in_(list(event_types)))
    best_sq = best.subquery("best")

    q = (
        select(
            Photo.id,
            Photo.event_id,
            Event.name,
            Event.type,
            Event.event_date,
            Photo.thumb_path,
            Photo.full_path,
            Photo.width,
            Photo.height,
            (1.0 - best_sq.c.d).label("similarity"),
            Photo.media_type,
            Photo.video_path,
            Photo.duration,
        )
        .join(best_sq, best_sq.c.photo_id == Photo.id)
        .join(Event, Event.id == Photo.event_id)
        .where(Photo.status == "done")
    )
    return [MatchRow(*row) for row in db.execute(q).all()]


def sort_matches(rows: Sequence[MatchRow]) -> list[MatchRow]:
    """Sort by event_date desc, then similarity desc (photo id as stable tie-break)."""
    return sorted(rows, key=lambda r: (-r.event_date.toordinal(), -r.similarity, str(r.photo_id)))


def merge_best(per_selfie: Sequence[Sequence[MatchRow]]) -> list[MatchRow]:
    """Merge per-selfie results keeping the best similarity per photo.

    The SQL query already does this via LEAST(); this pure helper exists for
    callers that query selfies separately (and documents/tests the rule).
    """
    best: dict[uuid.UUID, MatchRow] = {}
    for rows in per_selfie:
        for r in rows:
            cur = best.get(r.photo_id)
            if cur is None or r.similarity > cur.similarity:
                best[r.photo_id] = r
    return list(best.values())


def build_response(rows: Sequence[MatchRow], *, limit: int, offset: int) -> dict:
    """Build the public /api/match payload (no embeddings, no face data)."""
    ordered = sort_matches(rows)

    by_event: "OrderedDict[uuid.UUID, dict]" = OrderedDict()
    for r in ordered:
        entry = by_event.get(r.event_id)
        if entry is None:
            entry = by_event[r.event_id] = {
                "event_id": r.event_id,
                "name": r.event_name,
                "type": r.event_type,
                "event_date": r.event_date,
                "count": 0,
            }
        entry["count"] += 1

    page = ordered[offset : offset + limit]
    return {
        "total": len(ordered),
        "by_event": list(by_event.values()),
        "photos": [
            {
                "id": r.photo_id,
                "event_id": r.event_id,
                "thumb_url": storage.public_url(r.thumb_path),
                "full_url": storage.public_url(r.full_path),
                "width": r.width,
                "height": r.height,
                "media_type": r.media_type,
                "video_url": storage.public_url(r.video_path),
                "duration": r.duration,
                "similarity": round(float(r.similarity), 4),
            }
            for r in page
        ],
        "limit": limit,
        "offset": offset,
    }
