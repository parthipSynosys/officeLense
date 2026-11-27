"""Photo indexing pipeline (runs in RQ workers and in the bulk-index CLI).

Per photo:
  1. sha256 -> duplicates within the same event are skipped (at registration)
  2. decode, auto-rotate by EXIF, convert to RGB
  3. save full (max 1600px, JPEG q85) and thumb (max 400px, JPEG q75);
     keep the original under .../original/ if KEEP_ORIGINALS=true
  4. detect faces on the high-res image, embed each, insert rows into `faces`
  5. update photo.status / face_count; on error store the message, status=failed

Videos (media_type="video") take a different branch, see `_process_video`:
the file is kept under <event>/video/, frames are sampled for faces, and the
best frame becomes the poster saved as full/thumb.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal
from app.face.engine import get_engine
from app.models import Event, Face, Photo
from app.services import storage
from app.services.images import (
    FORMAT_EXTENSIONS,
    load_image,
    pil_to_bgr,
    InvalidImageError,
    resize_max,
    save_jpeg,
    sniff_image_type,
    validate_image_file,
)
from app.services.videos import (
    InvalidVideoError,
    analyze_video,
    read_head,
    sniff_video_type,
    validate_video_file,
)

log = logging.getLogger(__name__)

FULL_MAX_SIDE = 1600
FULL_QUALITY = 85
THUMB_MAX_SIDE = 400
THUMB_QUALITY = 75

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".3gp"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


class FileTooLargeError(ValueError):
    pass


class UnsupportedMediaError(ValueError):
    """Neither a supported image nor a supported video."""


def detect_media(path: Path) -> tuple[str, str]:
    """Validate a file by its content. Returns (media_type, extension).

    Raises UnsupportedMediaError, InvalidImageError or InvalidVideoError.
    """
    head = read_head(path)
    if sniff_image_type(head) is not None:
        return "photo", FORMAT_EXTENSIONS[validate_image_file(path)]
    if sniff_video_type(head) is not None:
        return "video", validate_video_file(path)
    raise UnsupportedMediaError("Not a supported image or video")


def max_bytes_for(media_type: str) -> int:
    s = get_settings()
    return s.MAX_VIDEO_BYTES if media_type == "video" else s.MAX_PHOTO_BYTES


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stream_to_file(src: BinaryIO, dest: Path, max_bytes: int) -> tuple[str, int]:
    """Copy a stream to `dest` while hashing it. Raises FileTooLargeError past max_bytes."""
    h = hashlib.sha256()
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dest, "wb") as out:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLargeError(f"File exceeds {max_bytes // (1024 * 1024)} MB")
                h.update(chunk)
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return h.hexdigest(), size


def sanitize_filename(name: str | None) -> str:
    base = os.path.basename((name or "photo").replace("\\", "/")).strip()
    return (base or "photo")[:255]


def register_photo(
    db: Session,
    *,
    event_id: uuid.UUID,
    staged_file: Path,
    file_hash: str,
    original_filename: str,
    photo_id: uuid.UUID | None = None,
) -> Photo | None:
    """Create a `queued` photo row for an already-validated file in the incoming dir.

    `staged_file` is renamed to its final incoming name. Returns None (and deletes
    the staged file) if the same content already exists in this event.
    """
    photo_id = photo_id or uuid.uuid4()
    exists = db.scalar(select(Photo.id).where(Photo.event_id == event_id, Photo.file_hash == file_hash))
    if exists:
        staged_file.unlink(missing_ok=True)
        return None

    media_type, ext = detect_media(staged_file)
    limit = max_bytes_for(media_type)
    if staged_file.stat().st_size > limit:
        staged_file.unlink(missing_ok=True)
        raise FileTooLargeError(f"File exceeds {limit // (1024 * 1024)} MB")
    rel = storage.rel_incoming(photo_id, ext)
    final = storage.abs_path(rel)
    os.replace(staged_file, final)

    photo = Photo(
        id=photo_id,
        event_id=event_id,
        original_filename=sanitize_filename(original_filename),
        media_type=media_type,
        file_hash=file_hash,
        source_path=rel,
        status="queued",
    )
    db.add(photo)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent upload of the same file.
        db.rollback()
        final.unlink(missing_ok=True)
        return None
    return photo


def _pick_source(photo: Photo) -> tuple[Path, str]:
    """Best available source for (re)indexing: staged upload > original > full (videos: > stored video)."""
    candidates = (
        (("incoming", photo.source_path), ("video", photo.video_path))
        if photo.media_type == "video"
        else (("incoming", photo.source_path), ("original", photo.original_path), ("full", photo.full_path))
    )
    for kind, rel in candidates:
        if rel:
            p = storage.abs_path(rel)
            if p.is_file():
                return p, kind
    raise FileNotFoundError("No source file available for this photo (upload it again)")


def process_photo(photo_id: uuid.UUID) -> dict:
    """Index a single photo. Never raises for per-photo errors: they are stored on the row."""
    settings = get_settings()
    with SessionLocal() as db:
        photo = db.get(Photo, photo_id)
        if photo is None:
            return {"status": "skipped", "reason": "photo deleted"}
        photo.status = "processing"
        photo.error = None
        db.commit()

        written: list[str] = []
        try:
            src, kind = _pick_source(photo)
            if photo.media_type == "video":
                return _process_video(db, photo, src, kind, written)
            img = load_image(src)

            full = resize_max(img, FULL_MAX_SIDE)
            thumb = resize_max(full, THUMB_MAX_SIDE)
            full_rel = storage.rel_full(photo.event_id, photo.id)
            thumb_rel = storage.rel_thumb(photo.event_id, photo.id)
            # When reindexing from the full image itself, don't overwrite it.
            if kind != "full":
                save_jpeg(full, storage.abs_path(full_rel), FULL_QUALITY)
                written.append(full_rel)
            save_jpeg(thumb, storage.abs_path(thumb_rel), THUMB_QUALITY)
            written.append(thumb_rel)

            original_rel = photo.original_path
            if kind == "incoming" and settings.KEEP_ORIGINALS:
                original_rel = storage.rel_original(photo.event_id, photo.id, src.suffix.lower())
                dst = storage.abs_path(original_rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                written.append(original_rel)

            # Detect on the high-resolution decoded image; embed on the same image.
            engine = get_engine()
            bgr = pil_to_bgr(img)
            detected = engine.detect(bgr)
            to_full = full.width / float(img.width)

            db.execute(delete(Face).where(Face.photo_id == photo.id))  # idempotent re-index
            for f in detected:
                emb = engine.embed(bgr, f)
                db.add(
                    Face(
                        photo_id=photo.id,
                        event_id=photo.event_id,
                        embedding=emb.tolist(),
                        box=f.box(scale=to_full, clip_w=full.width, clip_h=full.height),
                        score=f.score,
                    )
                )

            photo.full_path = full_rel
            photo.thumb_path = thumb_rel
            photo.original_path = original_rel
            photo.width, photo.height = full.width, full.height
            photo.face_count = len(detected)
            photo.status = "done"
            photo.error = None
            staged = photo.source_path
            photo.source_path = None
            db.commit()

            if kind == "incoming" and staged:
                storage.delete_rel(staged)
            return {"status": "done", "faces": len(detected)}

        except Exception as exc:  # record any failure on the photo row
            db.rollback()
            if isinstance(exc, (InvalidImageError, InvalidVideoError)):
                message = str(exc)[:1000]
            else:
                message = f"{type(exc).__name__}: {exc}"[:1000]
            log.warning("Indexing failed for photo %s: %s", photo_id, message)
            still_there = db.get(Photo, photo_id)
            if still_there is None or db.get(Event, still_there.event_id) is None:
                # Photo/event deleted while we were working: clean up what we wrote.
                storage.delete_photo_files(*written)
                return {"status": "skipped", "reason": "photo deleted"}
            still_there.status = "failed"
            still_there.error = message
            db.commit()
            return {"status": "failed", "error": message}


def _process_video(db: Session, photo: Photo, src: Path, kind: str, written: list[str]) -> dict:
    """Index a video: keep the file, sample frames for faces, save the poster frame."""
    settings = get_settings()

    # 1. Copy a fresh upload to its permanent home (re-index reads it from there).
    video_rel = photo.video_path
    if kind == "incoming":
        video_rel = storage.rel_video(photo.event_id, photo.id, src.suffix.lower())
        dst = storage.abs_path(video_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written.append(video_rel)
        src = dst

    # 2. Sample frames, detect + embed, merge repeated sightings of a person.
    result = analyze_video(
        src, get_engine(), sample_fps=settings.VIDEO_SAMPLE_FPS, max_frames=settings.VIDEO_MAX_FRAMES
    )

    # 3. Poster frame -> full / thumb, exactly like a photo.
    full = resize_max(result.poster_rgb, FULL_MAX_SIDE)
    thumb = resize_max(full, THUMB_MAX_SIDE)
    full_rel = storage.rel_full(photo.event_id, photo.id)
    thumb_rel = storage.rel_thumb(photo.event_id, photo.id)
    save_jpeg(full, storage.abs_path(full_rel), FULL_QUALITY)
    written.append(full_rel)
    save_jpeg(thumb, storage.abs_path(thumb_rel), THUMB_QUALITY)
    written.append(thumb_rel)

    # 4. Faces. Boxes are in the coordinates of the (possibly rotated) frame the
    #    face was seen in, scaled like the poster; "t" = seconds, "rot" = rotation.
    long_side = float(max(full.width, full.height))
    db.execute(delete(Face).where(Face.photo_id == photo.id))  # idempotent re-index
    for vf in result.faces:
        scale = long_side / max(vf.frame_w, vf.frame_h)
        box = vf.face.box(
            scale=scale, clip_w=round(vf.frame_w * scale), clip_h=round(vf.frame_h * scale)
        )
        box["t"] = round(vf.t, 2)
        box["rot"] = vf.rotation
        db.add(
            Face(
                photo_id=photo.id,
                event_id=photo.event_id,
                embedding=vf.embedding.tolist(),
                box=box,
                score=vf.face.score,
            )
        )

    photo.full_path = full_rel
    photo.thumb_path = thumb_rel
    photo.video_path = video_rel
    photo.duration = result.duration
    photo.width, photo.height = full.width, full.height
    photo.face_count = result.people  # distinct people, not stored samples
    photo.status = "done"
    photo.error = None
    staged = photo.source_path
    photo.source_path = None
    db.commit()

    if kind == "incoming" and staged:
        storage.delete_rel(staged)
    log.info(
        "Indexed video %s: %d frames sampled, %d people (%d face samples)",
        photo.id, result.frames_sampled, result.people, len(result.faces),
    )
    return {"status": "done", "faces": result.people}
