"""Indexing pipeline tests (need TEST_DATABASE_URL + models).

The RQ enqueue step is replaced by calling the job function directly, so these
tests exercise the exact code a worker runs without needing Redis.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import to_jpeg


@pytest.fixture
def auth(client, db):
    from app.models import Admin
    from app.security import hash_password

    db.add(Admin(email="ops@example.com", password_hash=hash_password("a-long-password")))
    db.commit()
    tok = client.post("/api/admin/login", json={"email": "ops@example.com", "password": "a-long-password"}).json()
    return {"Authorization": f"Bearer {tok['access_token']}"}


@pytest.fixture
def run_jobs_inline(monkeypatch):
    """Replace Redis enqueueing with immediate, in-process execution."""
    import app.api.admin.photos as photos_api
    from app.workers.tasks import index_photo_job

    def enqueue(ids):
        ids = list(ids)
        for pid in ids:
            index_photo_job(str(pid))
        return len(ids)

    monkeypatch.setattr(photos_api, "enqueue_photos", enqueue)


def _event(client, auth, **kw):
    body = {"name": "Annual Day", "type": "Cultural", "event_date": str(date(2025, 12, 1)), "is_published": True}
    body.update(kw)
    r = client.post("/api/admin/events", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_upload_index_match_delete(client, auth, run_jobs_inline, faces_bgr, sample_paths):
    from app.services import storage

    ev = _event(client, auth)
    astro_png = sample_paths["astronaut.png"].read_bytes()
    lena_jpg = sample_paths["lena.jpg"].read_bytes()
    files = [
        ("files", ("astro.png", astro_png, "image/png")),
        ("files", ("lena.jpg", lena_jpg, "image/jpeg")),
        ("files", ("dup.png", astro_png, "image/png")),  # same content -> duplicate
        ("files", ("notes.jpg", b"definitely not an image", "image/jpeg")),  # fake extension
    ]
    r = client.post(f"/api/admin/events/{ev['id']}/photos", files=files, headers=auth)
    assert r.status_code == 200, r.text
    res = r.json()
    assert [a["filename"] for a in res["accepted"]] == ["astro.png", "lena.jpg"]
    assert res["duplicates"] == ["dup.png"]
    assert [x["filename"] for x in res["rejected"]] == ["notes.jpg"]

    status = client.get(f"/api/admin/events/{ev['id']}/status", headers=auth).json()
    assert status == {"total": 2, "queued": 0, "processing": 0, "done": 2, "failed": 0, "faces": 2}

    page = client.get(f"/api/admin/events/{ev['id']}/photos", headers=auth).json()
    assert page["total"] == 2
    for p in page["items"]:
        assert p["status"] == "done" and p["face_count"] == 1
        assert max(p["width"], p["height"]) <= 1600
        full = storage.abs_path(p["full_url"].removeprefix("/photos/"))
        thumb = storage.abs_path(p["thumb_url"].removeprefix("/photos/"))
        assert full.is_file() and thumb.is_file()
    # Staged uploads are cleaned up after successful indexing (KEEP_ORIGINALS=false).
    assert not any(storage.incoming_dir().iterdir())

    # Public listing shows the event with its photo count.
    pub = client.get("/api/events").json()
    assert pub[0]["photo_count"] == 2 and pub[0]["cover_thumb_url"]

    # Guest selfie of the astronaut finds exactly the astronaut photo.
    r = client.post("/api/match", files=[("selfies", ("me.jpg", to_jpeg(faces_bgr["astronaut"]), "image/jpeg"))])
    body = r.json()
    assert body["total"] == 1, body
    astro_id = next(a["id"] for a in res["accepted"] if a["filename"] == "astro.png")
    assert body["photos"][0]["id"] == astro_id

    # Download returns an attachment.
    d = client.get(f"/api/photos/{astro_id}/download")
    assert d.status_code == 200
    assert d.headers["content-type"] == "image/jpeg"
    assert "attachment" in d.headers["content-disposition"]

    # Cover photo + reindex (from the stored full image) keep everything consistent.
    r = client.put(f"/api/admin/events/{ev['id']}", json={"cover_photo_id": astro_id}, headers=auth)
    assert r.status_code == 200 and r.json()["cover_photo_id"] == astro_id
    assert client.post(f"/api/admin/events/{ev['id']}/reindex", headers=auth).json() == {"queued": 2}
    status = client.get(f"/api/admin/events/{ev['id']}/status", headers=auth).json()
    assert status["done"] == 2 and status["faces"] == 2

    # Delete one photo, then the whole event: files + faces are gone.
    assert client.delete(f"/api/admin/photos/{astro_id}", headers=auth).status_code == 204
    assert client.get(f"/api/admin/events/{ev['id']}", headers=auth).json()["cover_photo_id"] is None
    assert client.delete(f"/api/admin/events/{ev['id']}", headers=auth).status_code == 204
    assert not (storage.photos_root() / ev["id"]).exists()
    r = client.post("/api/match", files=[("selfies", ("me.jpg", to_jpeg(faces_bgr["lena"]), "image/jpeg"))])
    assert r.json()["total"] == 0


def test_failed_photo_and_retry(client, auth, run_jobs_inline, db, sample_paths, monkeypatch):
    import app.services.indexing as indexing

    ev = _event(client, auth)
    real_load = indexing.load_image
    monkeypatch.setattr(indexing, "load_image", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    files = [("files", ("lena.jpg", sample_paths["lena.jpg"].read_bytes(), "image/jpeg"))]
    client.post(f"/api/admin/events/{ev['id']}/photos", files=files, headers=auth)

    page = client.get(f"/api/admin/events/{ev['id']}/photos?status=failed", headers=auth).json()
    assert page["total"] == 1
    assert "boom" in page["items"][0]["error"]

    monkeypatch.setattr(indexing, "load_image", real_load)
    assert client.post(f"/api/admin/events/{ev['id']}/retry-failed", headers=auth).json() == {"queued": 1}
    status = client.get(f"/api/admin/events/{ev['id']}/status", headers=auth).json()
    assert status["done"] == 1 and status["failed"] == 0 and status["faces"] == 1


def test_keep_originals(client, auth, run_jobs_inline, sample_paths, monkeypatch):
    from app.config import get_settings
    from app.models import Photo
    from app.services import storage

    monkeypatch.setattr(get_settings(), "KEEP_ORIGINALS", True)
    ev = _event(client, auth)
    files = [("files", ("astro.png", sample_paths["astronaut.png"].read_bytes(), "image/png"))]
    pid = client.post(f"/api/admin/events/{ev['id']}/photos", files=files, headers=auth).json()["accepted"][0]["id"]

    from app.db.session import SessionLocal

    with SessionLocal() as s:
        photo = s.get(Photo, __import__("uuid").UUID(pid))
        assert photo.original_path and photo.original_path.endswith(".png")
        assert storage.abs_path(photo.original_path).is_file()


def test_bulk_index_cli_is_resumable(client, auth, tmp_path, sample_paths, capsys):
    """Runs the CLI worker function in-process (the pool just calls this per file)."""
    from app.cli import _bulk_index_one

    ev = _event(client, auth)
    (tmp_path / "sub").mkdir()
    a = tmp_path / "a.png"
    b = tmp_path / "sub" / "b.jpg"
    bad = tmp_path / "broken.jpg"
    a.write_bytes(sample_paths["astronaut.png"].read_bytes())
    b.write_bytes(sample_paths["lena.jpg"].read_bytes())
    bad.write_bytes(b"\xff\xd8\xff garbage")

    first = [_bulk_index_one(ev["id"], str(p)) for p in (a, b, bad)]
    assert [r["status"] for r in first] == ["done", "done", "failed"]
    assert sum(r["faces"] for r in first) == 2
    # Source files are copied, never moved.
    assert a.exists() and b.exists()

    second = [_bulk_index_one(ev["id"], str(p)) for p in (a, b)]
    assert [r["status"] for r in second] == ["skipped", "skipped"]


def test_video_upload_index_match_download_delete(client, auth, run_jobs_inline, faces_bgr, tmp_path):
    """A video is indexed like a photo: poster thumb, faces, guest match, download, delete."""
    import cv2

    from app.services import storage
    from tests.test_videos import _canvas, _write_video

    ev = _event(client, auth)
    frames = [_canvas(None)] * 5 + [_canvas(faces_bgr["astronaut"], x=40)] * 30
    video = _write_video(tmp_path / "speech.mp4", frames, fps=10).read_bytes()

    r = client.post(
        f"/api/admin/events/{ev['id']}/photos",
        files=[("files", ("speech.mp4", video, "video/mp4"))],
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["accepted"]) == 1

    items = client.get(f"/api/admin/events/{ev['id']}/photos", headers=auth).json()["items"]
    assert len(items) == 1
    v = items[0]
    assert v["status"] == "done", v["error"]
    assert v["media_type"] == "video"
    assert v["face_count"] == 1
    assert v["video_url"].endswith(".mp4") and v["thumb_url"]
    assert v["duration"] == pytest.approx(3.5, abs=0.3)
    video_rel = v["video_url"].removeprefix("/photos/")
    assert storage.abs_path(video_rel).is_file()

    # No cover chosen -> the event thumbnail falls back to the first processed item.
    assert client.get(f"/api/admin/events/{ev['id']}", headers=auth).json()["cover_thumb_url"] == v["thumb_url"]
    stats = client.get("/api/admin/stats", headers=auth).json()
    assert stats["videos"] == 1 and stats["photos"] == 0

    # A guest selfie finds the video.
    ok, selfie = cv2.imencode(".jpg", faces_bgr["astronaut"])
    body = client.post("/api/match", files=[("selfies", ("s.jpg", selfie.tobytes(), "image/jpeg"))]).json()
    assert body["total"] == 1
    assert body["photos"][0]["media_type"] == "video"
    assert body["photos"][0]["video_url"] == v["video_url"]

    # Download serves the video file itself.
    d = client.get(f"/api/photos/{v['id']}/download")
    assert d.status_code == 200
    assert d.headers["content-type"] == "video/mp4"
    assert d.content == video
    assert ".mp4" in d.headers["content-disposition"]

    # Re-index reads from the stored video (the staged upload is gone).
    assert client.post(f"/api/admin/events/{ev['id']}/reindex", headers=auth).json() == {"queued": 1}
    again = client.get(f"/api/admin/events/{ev['id']}/photos", headers=auth).json()["items"][0]
    assert again["status"] == "done" and again["face_count"] == 1

    assert client.delete(f"/api/admin/photos/{v['id']}", headers=auth).status_code == 204
    assert not storage.abs_path(video_rel).exists()
