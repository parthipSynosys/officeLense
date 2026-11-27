"""Initial schema: admins, events, photos, faces (+ pgvector, HNSW index).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-27
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

EVENT_TYPES = ("Conference", "Workshop", "Cultural", "Sports", "Award Ceremony", "Team Outing", "Other")
PHOTO_STATUSES = ("queued", "processing", "done", "failed")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_photo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(_in("type", EVENT_TYPES), name="ck_events_type"),
    )
    op.create_index("ix_events_published_date", "events", ["is_published", "event_date"])

    op.create_table(
        "photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("full_path", sa.String(512), nullable=True),
        sa.Column("thumb_path", sa.String(512), nullable=True),
        sa.Column("original_path", sa.String(512), nullable=True),
        sa.Column("source_path", sa.String(512), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("face_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_id", "file_hash", name="uq_photos_event_hash"),
        sa.CheckConstraint(_in("status", PHOTO_STATUSES), name="ck_photos_status"),
    )
    op.create_index("ix_photos_event_status", "photos", ["event_id", "status"])
    op.create_index("ix_photos_event_created", "photos", ["event_id", "created_at"])

    # Circular reference: events.cover_photo_id -> photos.id
    op.create_foreign_key(
        "fk_events_cover_photo", "events", "photos", ["cover_photo_id"], ["id"], ondelete="SET NULL"
    )

    op.create_table(
        "faces",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "photo_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("photos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(128), nullable=False),
        sa.Column("box", postgresql.JSONB(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
    )
    op.create_index("ix_faces_event_id", "faces", ["event_id"])
    op.create_index("ix_faces_photo_id", "faces", ["photo_id"])
    # Approximate index for future unfiltered top-k queries. /api/match uses an
    # exact scan (see app/services/matching.py), so filtered results are complete.
    op.execute(
        "CREATE INDEX ix_faces_embedding_hnsw ON faces "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.drop_table("faces")
    op.drop_constraint("fk_events_cover_photo", "events", type_="foreignkey")
    op.drop_table("photos")
    op.drop_table("events")
    op.drop_table("admins")
