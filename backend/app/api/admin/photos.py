"""Admin photo upload, listing, indexing status, retry and re-index."""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.admin.events import get_event_or_404
from app.api.deps import get_current_admin
from app.config import get_settings
from app.db.session import get_db
from app.models import Face, Photo
from app.schemas import AdminPhotoOut, EventStatusOut, PhotoPage, UploadResult
from app.schemas.admin import ActionResult, UploadAccepted, UploadRejected
from app.services import storage
from app.services.images import InvalidImageError
from app.services.indexing import (
    FileTooLargeError,
    UnsupportedMediaError,
    register_photo,
    sanitize_filename,
    stream_to_file,
)
from app.services.videos import InvalidVideoError
from app.workers.queue import enqueue_photos

log = logging.getLogger(__name__)
router = APIRouter(tags=["admin: photos"], dependencies=[Depends(get_current_admin)])


def _photo_out(p: Photo) -> AdminPhotoOut:
    return AdminPhotoOut(
        id=p.id,
        event_id=p.event_id,
        original_filename=p.original_filename,
        status=p.status,  # type: ignore[arg-type]
        error=p.error,
        face_count=p.face_count,
        width=p.width,
        height=p.height,
        thumb_url=storage.public_url(p.thumb_path),
        full_url=storage.public_url(p.full_path),
        media_type=p.media_type,  # type: ignore[arg-type]
        video_url=storage.public_url(p.video_path),
        duration=p.duration,
        created_at=p.created_at,
    )


def _enqueue_or_fail(db: Session, photo_ids: list[uuid.UUID]) -> int:
    """Enqueue jobs; if Redis is down, mark the photos failed so 'retry' can recover them."""
    if not photo_ids:
        return 0
    try:
        return enqueue_photos(photo_ids)
    except Exception as exc:
        log.error("Could not enqueue %d photos: %s", len(photo_ids), exc)
        db.execute(
            update(Photo)
            .where(Photo.id.in_(photo_ids))
            .values(status="failed", error="Queue unavailable — use 'Retry failed' once Redis is running")
        )
        db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "QUEUE_UNAVAILABLE", "message": "Job queue unavailable; photos marked failed"},
        ) from exc


@router.post(
    "/events/{event_id}/photos",
    response_model=UploadResult,
    summary="Upload photos and videos (multipart, field 'files', many files) and enqueue indexing",
)
def upload_photos(
    event_id: uuid.UUID,
    files: list[UploadFile] = File(..., description="Images (JPEG, PNG, WebP, HEIC; max 30 MB) or videos (MP4, MOV, WebM, MKV, AVI; max 500 MB)"),
    db: Session = Depends(get_db),
) -> UploadResult:
    get_event_or_404(db, event_id)
    settings = get_settings()
    # The real per-type limit is checked once the content type is known.
    max_bytes = max(settings.MAX_PHOTO_BYTES, settings.MAX_VIDEO_BYTES)
    incoming = storage.incoming_dir()

    accepted: list[UploadAccepted] = []
    duplicates: list[str] = []
    rejected: list[UploadRejected] = []

    for upload in files:
        name = sanitize_filename(upload.filename)
        photo_id = uuid.uuid4()
        tmp = incoming / f"{photo_id}.upload"
        try:
            file_hash, _size = stream_to_file(upload.file, tmp, max_bytes)
            photo = register_photo(
                db,
                event_id=event_id,
                staged_file=tmp,
                file_hash=file_hash,
                original_filename=name,
                photo_id=photo_id,
            )
            if photo is None:
                duplicates.append(name)
            else:
                accepted.append(UploadAccepted(id=photo.id, filename=name))
        except FileTooLargeError as exc:
            rejected.append(UploadRejected(filename=name, error=str(exc)))
        except (InvalidImageError, InvalidVideoError, UnsupportedMediaError) as exc:
            tmp.unlink(missing_ok=True)
            message = (
                str(exc)
                if isinstance(exc, InvalidVideoError)
                else "Not a supported image (JPEG, PNG, WebP, HEIC) or video (MP4, MOV, WebM, MKV, AVI)"
            )
            rejected.append(UploadRejected(filename=name, error=message))
        except Exception as exc:  # keep going: one bad file must not stop the batch
            tmp.unlink(missing_ok=True)
            db.rollback()
            log.exception("Upload failed for %s", name)
            rejected.append(UploadRejected(filename=name, error=f"Upload failed: {type(exc).__name__}"))
        finally:
            upload.file.close()

    _enqueue_or_fail(db, [a.id for a in accepted])
    return UploadResult(accepted=accepted, duplicates=duplicates, rejected=rejected)


@router.get("/events/{event_id}/photos", response_model=PhotoPage, summary="Paginated photo list")
def list_photos(
    event_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=200),
    status_filter: Literal["queued", "processing", "done", "failed"] | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
) -> PhotoPage:
    get_event_or_404(db, event_id)
    base = select(Photo).where(Photo.event_id == event_id)
    if status_filter:
        base = base.where(Photo.status == status_filter)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Photo.created_at.desc(), Photo.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return PhotoPage(items=[_photo_out(p) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/events/{event_id}/status", response_model=EventStatusOut, summary="Indexing progress")
def event_status(event_id: uuid.UUID, db: Session = Depends(get_db)) -> EventStatusOut:
    get_event_or_404(db, event_id)
    counts = dict(
        db.execute(select(Photo.status, func.count()).where(Photo.event_id == event_id).group_by(Photo.status)).all()
    )
    faces = db.scalar(select(func.count()).select_from(Face).where(Face.event_id == event_id)) or 0
    return EventStatusOut(
        total=sum(counts.values()),
        queued=counts.get("queued", 0),
        processing=counts.get("processing", 0),
        done=counts.get("done", 0),
        failed=counts.get("failed", 0),
        faces=faces,
    )


@router.post("/events/{event_id}/retry-failed", response_model=ActionResult, summary="Re-queue failed photos")
def retry_failed(event_id: uuid.UUID, db: Session = Depends(get_db)) -> ActionResult:
    get_event_or_404(db, event_id)
    ids = list(db.scalars(select(Photo.id).where(Photo.event_id == event_id, Photo.status == "failed")).all())
    if ids:
        db.execute(update(Photo).where(Photo.id.in_(ids)).values(status="queued", error=None))
        db.commit()
    return ActionResult(queued=_enqueue_or_fail(db, ids))


@router.post("/events/{event_id}/reindex", response_model=ActionResult, summary="Re-run face indexing for all photos")
def reindex_event(event_id: uuid.UUID, db: Session = Depends(get_db)) -> ActionResult:
    get_event_or_404(db, event_id)
    ids = list(db.scalars(select(Photo.id).where(Photo.event_id == event_id)).all())
    if ids:
        db.execute(update(Photo).where(Photo.id.in_(ids)).values(status="queued", error=None))
        db.commit()
    return ActionResult(queued=_enqueue_or_fail(db, ids))


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a photo + its faces")
def delete_photo(photo_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "Photo not found"})
    paths = (photo.full_path, photo.thumb_path, photo.original_path, photo.source_path, photo.video_path)
    db.delete(photo)  # faces cascade; events.cover_photo_id is SET NULL
    db.commit()
    storage.delete_photo_files(*paths)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
