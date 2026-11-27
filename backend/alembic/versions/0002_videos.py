"""Video support: photos.media_type / video_path / duration.

A video is stored as a row in `photos` with media_type='video'. Its poster frame
is saved as the usual full/thumb JPEGs, so every existing listing, cover and
match query keeps working; `video_path` points at the playable file.

Revision ID: 0002_videos
Revises: 0001_initial
Create Date: 2026-11-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_videos"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "photos",
        sa.Column("media_type", sa.String(8), nullable=False, server_default="photo"),
    )
    op.add_column("photos", sa.Column("video_path", sa.String(512), nullable=True))
    op.add_column("photos", sa.Column("duration", sa.Float(), nullable=True))
    op.create_check_constraint("ck_photos_media_type", "photos", "media_type IN ('photo', 'video')")


def downgrade() -> None:
    op.drop_constraint("ck_photos_media_type", "photos", type_="check")
    op.drop_column("photos", "duration")
    op.drop_column("photos", "video_path")
    op.drop_column("photos", "media_type")
