"""Admin API schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventType = Literal["Conference", "Workshop", "Cultural", "Sports", "Award Ceremony", "Team Outing", "Other"]
PhotoStatus = Literal["queued", "processing", "done", "failed"]
MediaType = Literal["photo", "video"]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    email: str


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: EventType
    event_date: date
    description: str = Field(default="", max_length=5000)
    is_published: bool = False

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be blank")
        return v


class EventUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: EventType | None = None
    event_date: date | None = None
    description: str | None = Field(default=None, max_length=5000)
    is_published: bool | None = None
    # Explicit null clears the cover photo.
    cover_photo_id: uuid.UUID | None = None


class AdminEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    event_date: date
    description: str
    cover_photo_id: uuid.UUID | None
    cover_thumb_url: str | None = None
    is_published: bool
    created_at: datetime
    updated_at: datetime
    photo_count: int = 0
    done_count: int = 0
    failed_count: int = 0
    face_count: int = 0


class AdminPhotoOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    original_filename: str
    status: PhotoStatus
    error: str | None
    face_count: int
    width: int | None
    height: int | None
    thumb_url: str | None
    full_url: str | None
    media_type: MediaType = "photo"
    video_url: str | None = None
    duration: float | None = None  # seconds, videos only
    created_at: datetime


class PhotoPage(BaseModel):
    items: list[AdminPhotoOut]
    total: int
    page: int
    page_size: int


class EventStatusOut(BaseModel):
    total: int
    queued: int
    processing: int
    done: int
    failed: int
    faces: int


class UploadAccepted(BaseModel):
    id: uuid.UUID
    filename: str


class UploadRejected(BaseModel):
    filename: str
    error: str


class UploadResult(BaseModel):
    accepted: list[UploadAccepted]
    duplicates: list[str]
    rejected: list[UploadRejected]


class StatsOut(BaseModel):
    events: int
    published_events: int
    photos: int
    videos: int = 0
    faces: int
    failed: int
    processing: int
    queue: int | None  # None when Redis is unreachable


class ActionResult(BaseModel):
    queued: int
