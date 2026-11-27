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

Using LEAST() across all selfie embeddings and the best face per photo implements
the merge rule "per photo keep the BEST similarity across all selfies".

Two refinements on top (both query-time, no re-indexing):
  * low-quality gallery faces (weak detection / tiny) need a higher similarity,
    which removes most "wrong person" results;
  * query expansion from the most certain matches finds the guest in photos
    whose lighting/angle differ a lot from the selfie (fewer missing photos).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import Event, Face, Photo
from app.services import storage

# --- Precision: weak gallery faces must match more strongly ------------------
# Blurry, side-on, half-hidden or tiny faces give noisy embeddings that can
# cross the threshold for the wrong person. They still match, but only when the
# similarity is clearly higher. (Applied at query time: no re-indexing needed.)
WEAK_FACE_SCORE = 0.85  # YuNet confidence below this = low-quality detection
TINY_FACE_PX = 36  # face box side (stored-image pixels) below this = tiny face
LOW_QUALITY_PENALTY = 0.06  # extra similarity required for such faces

# --- Recall: query expansion ---------------------------------------------------
# Event photos differ from a selfie (lighting, angle, camera), so some real
# matches score just under the threshold. Faces that matched the selfie very
# strongly are certainly the guest AND were taken in the event's conditions, so
# they are used as extra queries. A face found this way must be close to one of
# those seeds AND still reasonably close to the selfie itself.
EXPAND_MIN_SIM = 0.50  # direct similarity a face needs to become a seed
EXPAND_MARGIN = 0.10  # ...and at least threshold + this
EXPAND_MAX_SEEDS = 8
EXPAND_SEED_SIM = 0.50  # face-to-seed similarity needed (same person, same event)
EXPAND_SELFIE_FLOOR = 0.07  # face-to-selfie similarity still >= threshold - this


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
    # Videos: seconds into the clip where the best-matching face was seen.
    match_time: float | None = None


@dataclass(frozen=True)
class _Hit:
    face_id: int
    distance: float  # cosine distance to the selfie(s)
    t: float | None
    good_quality: bool


def _least_distance(embeddings: Sequence[np.ndarray]):
    distances = [Face.embedding.cosine_distance(np.asarray(e, dtype=np.float32).tolist()) for e in embeddings]
    return distances[0] if len(distances) == 1 else func.least(*distances)


def _quality_penalty():
    """SQL expression: extra cosine distance margin required for low-quality faces."""
    w = Face.box["w"].as_float()
    h = Face.box["h"].as_float()
    low = or_(Face.score < WEAK_FACE_SCORE, func.least(w, h) < TINY_FACE_PX)
    return case((low, LOW_QUALITY_PENALTY), else_=0.0)


def _scan(
    db: Session,
    selfie_dist,
    condition,
    *,
    event_ids: Sequence[uuid.UUID] | None,
    event_types: Sequence[str] | None,
) -> dict[uuid.UUID, _Hit]:
    """Best face (closest to the selfies) per photo among faces meeting `condition`.

    Exact scan: no `ORDER BY distance LIMIT k`, so the HNSW index is never used
    and filtered results are complete.
    """
    penalty = _quality_penalty()
    q = (
        select(Face.photo_id, Face.id, selfie_dist.label("d"), Face.box["t"].as_float().label("t"), penalty.label("p"))
        .join(Event, Event.id == Face.event_id)
        .where(Event.is_published.is_(True))
        .where(condition(penalty))
        .distinct(Face.photo_id)
        .order_by(Face.photo_id, selfie_dist)
    )
    if event_ids:
        q = q.where(Face.event_id.in_(list(event_ids)))
    if event_types:
        q = q.where(Event.type.in_(list(event_types)))
    return {
        photo_id: _Hit(face_id=face_id, distance=float(d), t=t, good_quality=float(p) == 0.0)
        for photo_id, face_id, d, t, p in db.execute(q).all()
    }


def find_matches(
    db: Session,
    embeddings: Sequence[np.ndarray],
    *,
    threshold: float,
    event_ids: Sequence[uuid.UUID] | None = None,
    event_types: Sequence[str] | None = None,
    expand: bool = True,
) -> list[MatchRow]:
    """Return every matching photo/video (best similarity per item), unsorted."""
    if not embeddings:
        return []
    threshold = float(threshold)
    max_distance = 1.0 - threshold
    dist = _least_distance(embeddings)
    filters = {"event_ids": event_ids, "event_types": event_types}

    # 1. Direct matches against the selfie(s), stricter for low-quality faces.
    hits = _scan(db, dist, lambda penalty: dist <= max_distance - penalty, **filters)

    # 2. Query expansion from the most certain, good-quality direct matches.
    if expand and hits:
        seed_sim = max(EXPAND_MIN_SIM, threshold + EXPAND_MARGIN)
        seeds = sorted(
            (h for h in hits.values() if h.good_quality and 1.0 - h.distance >= seed_sim),
            key=lambda h: h.distance,
        )[:EXPAND_MAX_SEEDS]
        if seeds:
            seed_embs = db.scalars(select(Face.embedding).where(Face.id.in_([h.face_id for h in seeds]))).all()
            seed_dist = _least_distance(seed_embs)
            floor = 1.0 - (threshold - EXPAND_SELFIE_FLOOR)
            extra = _scan(
                db,
                dist,
                lambda penalty: and_(seed_dist <= (1.0 - EXPAND_SEED_SIM) - penalty, dist <= floor - penalty),
                **filters,
            )
            for photo_id, hit in extra.items():
                hits.setdefault(photo_id, hit)

    if not hits:
        return []

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
            Photo.media_type,
            Photo.video_path,
            Photo.duration,
        )
        .join(Event, Event.id == Photo.event_id)
        .where(Photo.id.in_(list(hits)))
        .where(Photo.status == "done")
    )
    rows = []
    for pid, eid, name, etype, edate, thumb, full, w, h, media, video, duration in db.execute(q).all():
        hit = hits[pid]
        rows.append(
            MatchRow(
                pid, eid, name, etype, edate, thumb, full, w, h,
                similarity=1.0 - hit.distance,
                media_type=media,
                video_path=video,
                duration=duration,
                match_time=hit.t if media == "video" else None,
            )
        )
    return rows


def count_pending(
    db: Session,
    *,
    event_ids: Sequence[uuid.UUID] | None = None,
    event_types: Sequence[str] | None = None,
) -> int:
    """Photos/videos in the searched (published) events that are still being indexed."""
    q = (
        select(func.count())
        .select_from(Photo)
        .join(Event, Event.id == Photo.event_id)
        .where(Event.is_published.is_(True))
        .where(Photo.status.in_(("queued", "processing")))
    )
    if event_ids:
        q = q.where(Photo.event_id.in_(list(event_ids)))
    if event_types:
        q = q.where(Event.type.in_(list(event_types)))
    return int(db.scalar(q) or 0)


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


def build_response(rows: Sequence[MatchRow], *, limit: int, offset: int, pending: int = 0) -> dict:
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
                "match_time": None if r.match_time is None else round(float(r.match_time), 2),
            }
            for r in page
        ],
        "limit": limit,
        "offset": offset,
        "pending": pending,
    }
