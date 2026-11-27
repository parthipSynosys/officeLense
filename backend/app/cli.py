"""EventLens command-line tools.

    python -m app.cli create-admin --email admin@example.com
    python -m app.cli create-admin --email admin@example.com --reset   # change password
    python -m app.cli bulk-index --event <event_uuid> --dir /data/raw/annual-day [--workers 4]

bulk-index indexes photos already on the server directly (no Redis needed):
  * recursive scan for .jpg/.jpeg/.png/.webp/.heic/.heif
  * resumable: files whose sha256 is already indexed in the event are skipped,
    previously failed/unfinished ones are retried
  * parallel worker processes (default WORKER_CONCURRENCY), tqdm progress bar
  * writes a failed-files report and prints a summary at the end
Source files are COPIED, never moved or modified.
"""

from __future__ import annotations

import argparse
import getpass
import multiprocessing as mp
import shutil
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# create-admin
# ---------------------------------------------------------------------------


def cmd_create_admin(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Admin
    from app.security import MAX_PASSWORD_BYTES, hash_password

    email = args.email.strip().lower()  # username or email
    if len(email) < 3:
        print("Error: username must be at least 3 characters", file=sys.stderr)
        return 2

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            print("Error: passwords do not match", file=sys.stderr)
            return 2
    if len(password) < 6:
        print("Error: password must be at least 6 characters", file=sys.stderr)
        return 2
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        print("Error: password must be at most 72 bytes", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        existing = db.scalar(select(Admin).where(Admin.email == email))
        if existing and not args.reset:
            print(f"Error: admin {email} already exists (use --reset to change the password)", file=sys.stderr)
            return 1
        if existing:
            existing.password_hash = hash_password(password)
            action = "updated"
        else:
            db.add(Admin(email=email, password_hash=hash_password(password)))
            action = "created"
        db.commit()
    print(f"Admin {email} {action}.")
    return 0


# ---------------------------------------------------------------------------
# bulk-index
# ---------------------------------------------------------------------------


def _bulk_init() -> None:
    """Runs once in each worker process: limit OpenCV threads, load models."""
    import cv2

    cv2.setNumThreads(1)
    from app.face.engine import load_engine

    load_engine()


def _bulk_index_one(event_id_str: str, path_str: str) -> dict:
    """Index one file. Returns {"path", "status": done|skipped|failed, "faces", "error"}."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Photo
    from app.services import storage
    from app.services.images import InvalidImageError
    from app.services.indexing import UnsupportedMediaError, detect_media, process_photo, register_photo, sha256_file
    from app.services.videos import InvalidVideoError

    event_id = uuid.UUID(event_id_str)
    path = Path(path_str)
    try:
        file_hash = sha256_file(path)
        with SessionLocal() as db:
            existing = db.scalar(select(Photo).where(Photo.event_id == event_id, Photo.file_hash == file_hash))
            if existing is not None and existing.status == "done":
                return {"path": path_str, "status": "skipped", "faces": existing.face_count}

            if existing is not None:
                # Resume a previously failed / interrupted photo.
                photo_id = existing.id
                has_source = any(
                    rel and storage.abs_path(rel).is_file()
                    for rel in (
                        (existing.source_path, existing.video_path)
                        if existing.media_type == "video"
                        else (existing.source_path, existing.original_path, existing.full_path)
                    )
                )
                if not has_source:
                    _, ext = detect_media(path)
                    rel = storage.rel_incoming(photo_id, ext)
                    shutil.copy2(path, storage.abs_path(rel))
                    existing.source_path = rel
                existing.status = "queued"
                db.commit()
            else:
                staged = storage.incoming_dir() / f"{uuid.uuid4()}.bulk"
                shutil.copy2(path, staged)
                try:
                    photo = register_photo(
                        db,
                        event_id=event_id,
                        staged_file=staged,
                        file_hash=file_hash,
                        original_filename=path.name,
                    )
                except BaseException:
                    staged.unlink(missing_ok=True)
                    raise
                if photo is None:  # indexed concurrently by another process
                    return {"path": path_str, "status": "skipped", "faces": 0}
                photo_id = photo.id

        result = process_photo(photo_id)
        if result.get("status") == "done":
            return {"path": path_str, "status": "done", "faces": int(result.get("faces", 0))}
        return {"path": path_str, "status": "failed", "faces": 0, "error": result.get("error") or result.get("reason")}
    except (InvalidImageError, InvalidVideoError, UnsupportedMediaError) as exc:
        return {"path": path_str, "status": "failed", "faces": 0, "error": f"Invalid file: {exc}"}
    except Exception as exc:
        return {"path": path_str, "status": "failed", "faces": 0, "error": f"{type(exc).__name__}: {exc}"}


def cmd_bulk_index(args: argparse.Namespace) -> int:
    from tqdm import tqdm

    from app.config import get_settings
    from app.db.session import SessionLocal
    from app.models import Event
    from app.services.indexing import MEDIA_EXTENSIONS

    try:
        event_id = uuid.UUID(args.event)
    except ValueError:
        print("Error: --event must be an event UUID", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        event = db.get(Event, event_id)
        if event is None:
            print(f"Error: event {event_id} not found", file=sys.stderr)
            return 1
        event_name = event.name

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        return 2

    pattern = root.rglob("*") if not args.no_recursive else root.glob("*")
    files = sorted(str(p) for p in pattern if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS)
    if not files:
        print("No image or video files found.")
        return 0

    workers = max(1, args.workers or get_settings().WORKER_CONCURRENCY)
    print(f"Indexing {len(files)} files into '{event_name}' with {workers} worker process(es)...")

    counts = {"done": 0, "skipped": 0, "failed": 0}
    faces = 0
    failures: list[tuple[str, str]] = []
    started = time.monotonic()

    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_bulk_init) as pool:
        futures = [pool.submit(_bulk_index_one, str(event_id), f) for f in files]
        with tqdm(total=len(files), unit="photo", dynamic_ncols=True) as bar:
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception as exc:  # worker crashed
                    res = {"path": "?", "status": "failed", "faces": 0, "error": f"worker error: {exc}"}
                counts[res["status"]] += 1
                if res["status"] == "done":
                    faces += res["faces"]
                elif res["status"] == "failed":
                    failures.append((res["path"], res.get("error") or "unknown error"))
                bar.set_postfix(done=counts["done"], skipped=counts["skipped"], failed=counts["failed"], faces=faces)
                bar.update(1)

    elapsed = time.monotonic() - started
    print("\n=== Bulk index summary ===")
    print(f"Event:            {event_name} ({event_id})")
    print(f"Files found:      {len(files)}")
    print(f"Indexed now:      {counts['done']}")
    print(f"Skipped (done):   {counts['skipped']}")
    print(f"Failed:           {counts['failed']}")
    print(f"Faces found:      {faces}")
    rate = counts["done"] / elapsed if elapsed > 0 else 0.0
    print(f"Time:             {elapsed:.1f}s ({rate:.2f} photos/s)")

    if failures:
        report = Path(args.report or f"bulk-index-failed-{datetime.now():%Y%m%d-%H%M%S}.txt")
        report.write_text("".join(f"{p}\t{e}\n" for p, e in failures), encoding="utf-8")
        print(f"Failed files report: {report.resolve()}")
        print("Re-run the same command to retry failed files.")
        return 1
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m app.cli", description="EventLens admin tools")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Create an admin user (prompts for the password)")
    p.add_argument("--email", "--username", dest="email", required=True, help="admin username (or email)")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin (for scripts)")
    p.add_argument("--reset", action="store_true", help="update the password if the admin exists")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("bulk-index", help="Index photos already on the server into an event")
    p.add_argument("--event", required=True, help="event UUID (create the event in the admin UI first)")
    p.add_argument("--dir", required=True, help="directory containing photos (scanned recursively)")
    p.add_argument("--workers", type=int, default=0, help="parallel processes (default WORKER_CONCURRENCY)")
    p.add_argument("--no-recursive", action="store_true", help="only scan the top-level directory")
    p.add_argument("--report", help="path for the failed-files report")
    p.set_defaults(func=cmd_bulk_index)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
