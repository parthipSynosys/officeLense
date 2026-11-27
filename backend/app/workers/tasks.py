"""RQ job entry points (imported by worker processes)."""

from __future__ import annotations

import uuid

from app.services.indexing import process_photo


def index_photo_job(photo_id: str) -> dict:
    """Index one photo. Errors are recorded on the photo row, not raised."""
    return process_photo(uuid.UUID(photo_id))
