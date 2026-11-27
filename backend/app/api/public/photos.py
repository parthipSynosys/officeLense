"""Public photo download."""

from __future__ import annotations

import mimetypes
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Event, Photo
from app.services import storage

router = APIRouter(tags=["public"])


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "photo"


@router.get(
    "/photos/{photo_id}/download",
    summary="Download a photo or video (attachment) from a published event",
    response_class=FileResponse,
)
def download_photo(photo_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    row = db.execute(
        select(Photo.full_path, Photo.video_path, Photo.media_type, Event.name)
        .join(Event, Event.id == Photo.event_id)
        .where(Photo.id == photo_id, Photo.status == "done", Event.is_published.is_(True))
    ).first()
    not_found = HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "Photo not found"})
    rel = row.video_path if row is not None and row.media_type == "video" else row.full_path if row else None
    if not rel:
        raise not_found
    path = storage.abs_path(rel)
    if not path.is_file():
        raise not_found
    ext = path.suffix.lower() or ".jpg"
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        filename=f"{_slug(row.name)}-{photo_id.hex[:8]}{ext}",  # sets Content-Disposition: attachment
        headers={"Cache-Control": "public, max-age=86400"},
    )
