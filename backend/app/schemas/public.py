"""Public API schemas. Nothing here ever contains face boxes or embeddings."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel


class PublicEventOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    date: date
    cover_thumb_url: str | None
    photo_count: int


class EventTypeList(BaseModel):
    types: list[str]


class MatchByEvent(BaseModel):
    event_id: uuid.UUID
    name: str
    type: str
    event_date: date
    count: int


class MatchPhoto(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    thumb_url: str | None
    full_url: str | None
    width: int | None
    height: int | None
    media_type: str = "photo"
    video_url: str | None = None
    duration: float | None = None
    similarity: float
    # Videos: seconds into the clip where this guest was seen (start playback here).
    match_time: float | None = None


class MatchResponse(BaseModel):
    total: int
    by_event: list[MatchByEvent]
    photos: list[MatchPhoto]
    limit: int
    offset: int
    # Photos/videos in the searched events still being indexed (not searchable yet).
    pending: int = 0


class SelfieErrorOut(BaseModel):
    index: int
    code: str
    message: str


class HealthOut(BaseModel):
    status: str
    models_loaded: bool
    db_ok: bool
    redis_ok: bool
    queue_size: int | None
