"""ORM models. The Alembic migration in `alembic/versions` mirrors these exactly.

Relationships are intentionally not declared: all deletes are handled by
`ON DELETE CASCADE` in PostgreSQL, and queries are written explicitly, which
keeps the circular events <-> photos (cover photo) reference simple.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 128

EVENT_TYPES: tuple[str, ...] = (
    "Conference",
    "Workshop",
    "Cultural",
    "Sports",
    "Award Ceremony",
    "Team Outing",
    "Other",
)

PHOTO_STATUSES: tuple[str, ...] = ("queued", "processing", "done", "failed")
MEDIA_TYPES: tuple[str, ...] = ("photo", "video")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(_in_list("type", EVENT_TYPES), name="ck_events_type"),
        Index("ix_events_published_date", "is_published", "event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    cover_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("photos.id", ondelete="SET NULL", use_alter=True, name="fk_events_cover_photo"),
        nullable=True,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (
        UniqueConstraint("event_id", "file_hash", name="uq_photos_event_hash"),
        CheckConstraint(_in_list("status", PHOTO_STATUSES), name="ck_photos_status"),
        CheckConstraint(_in_list("media_type", MEDIA_TYPES), name="ck_photos_media_type"),
        Index("ix_photos_event_status", "event_id", "status"),
        Index("ix_photos_event_created", "event_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # "photo" or "video". A video's poster frame is stored as full/thumb like a photo.
    media_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default="photo", server_default="photo"
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # All *_path columns are RELATIVE to PHOTOS_DIR (e.g. "<event>/full/<id>.jpg").
    full_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumb_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Videos only: the playable file ("<event>/video/<id>.<ext>") and its length in seconds.
    video_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Uploaded file waiting to be indexed (PHOTOS_DIR/_incoming/...). Cleared on success.
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    face_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Face(Base):
    __tablename__ = "faces"
    __table_args__ = (
        Index("ix_faces_event_id", "event_id"),
        Index("ix_faces_photo_id", "photo_id"),
        Index(
            "ix_faces_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photos.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    # Box in pixel coordinates of the stored "full" (max 1600px) image. For videos
    # the box is in the (equally sized) frame it was seen in, plus "t" = seconds.
    box: Mapped[dict] = mapped_column(JSONB, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
