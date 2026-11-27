"""Filesystem layout for photos.

    PHOTOS_DIR/
      _incoming/<photo_id>.<ext>          uploads waiting to be indexed
      <event_id>/full/<photo_id>.jpg      max 1600px, JPEG q85
      <event_id>/thumb/<photo_id>.jpg     max 400px,  JPEG q75
      <event_id>/original/<photo_id>.<ext>  only if KEEP_ORIGINALS=true
      <event_id>/video/<photo_id>.<ext>   videos (always kept; full/thumb hold the poster)

Database columns store paths RELATIVE to PHOTOS_DIR, built only from UUIDs,
so they can never escape the photos directory.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.config import get_settings

INCOMING = "_incoming"


def photos_root() -> Path:
    return get_settings().PHOTOS_DIR.resolve()


def incoming_dir() -> Path:
    d = photos_root() / INCOMING
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel_incoming(photo_id: uuid.UUID, ext: str) -> str:
    return f"{INCOMING}/{photo_id}{ext}"


def rel_full(event_id: uuid.UUID, photo_id: uuid.UUID) -> str:
    return f"{event_id}/full/{photo_id}.jpg"


def rel_thumb(event_id: uuid.UUID, photo_id: uuid.UUID) -> str:
    return f"{event_id}/thumb/{photo_id}.jpg"


def rel_original(event_id: uuid.UUID, photo_id: uuid.UUID, ext: str) -> str:
    return f"{event_id}/original/{photo_id}{ext}"


def rel_video(event_id: uuid.UUID, photo_id: uuid.UUID, ext: str) -> str:
    return f"{event_id}/video/{photo_id}{ext}"


def abs_path(rel: str) -> Path:
    """Resolve a stored relative path, refusing anything outside PHOTOS_DIR."""
    root = photos_root()
    p = (root / rel).resolve()
    if root != p and root not in p.parents:
        raise ValueError(f"Path escapes PHOTOS_DIR: {rel}")
    return p


def public_url(rel: str | None) -> str | None:
    if not rel:
        return None
    return f"{get_settings().PUBLIC_PHOTOS_URL.rstrip('/')}/{rel}"


def delete_rel(rel: str | None) -> None:
    if not rel:
        return
    try:
        abs_path(rel).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def delete_photo_files(*rels: str | None) -> None:
    for rel in rels:
        delete_rel(rel)


def delete_event_files(event_id: uuid.UUID) -> None:
    """Permanently remove every stored file of an event."""
    d = photos_root() / str(event_id)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
