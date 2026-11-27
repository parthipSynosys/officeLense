"""API tests.

The first group needs no database (auth guard, /match validation + error codes,
privacy). The second group needs TEST_DATABASE_URL (filters, pagination, CRUD).
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date

import cv2
import numpy as np
import pytest

from tests.conftest import augment, to_jpeg

ADMIN_ROUTES = [
    ("get", "/api/admin/stats"),
    ("get", "/api/admin/events"),
    ("post", "/api/admin/events"),
    ("put", f"/api/admin/events/{uuid.uuid4()}"),
    ("delete", f"/api/admin/events/{uuid.uuid4()}"),
    ("post", f"/api/admin/events/{uuid.uuid4()}/photos"),
    ("get", f"/api/admin/events/{uuid.uuid4()}/photos"),
    ("get", f"/api/admin/events/{uuid.uuid4()}/status"),
    ("post", f"/api/admin/events/{uuid.uuid4()}/retry-failed"),
    ("post", f"/api/admin/events/{uuid.uuid4()}/reindex"),
    ("delete", f"/api/admin/photos/{uuid.uuid4()}"),
]


# ---------------------------------------------------------------------------
# No database required
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_admin_routes_require_auth(client_no_models, method, path):
    r = getattr(client_no_models, method)(path)
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("token", ["garbage", "a.b.c"])
def test_admin_routes_reject_bad_token(client_no_models, token):
    r = client_no_models.get("/api/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_admin_rejects_token_signed_with_other_secret(client_no_models):
    import jwt

    forged = jwt.encode({"sub": "1", "typ": "access", "iat": 1, "exp": 9999999999}, "y" * 40, algorithm="HS256")
    r = client_no_models.get("/api/admin/stats", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_openapi_docs_available(client_no_models):
    assert client_no_models.get("/api/docs").status_code == 200
    spec = client_no_models.get("/api/openapi.json").json()
    assert "/api/match" in spec["paths"]


def _post_match(client, images: list[bytes], **fields):
    """POST /api/match with selfies + form fields (list values become repeated fields)."""
    files = [("selfies", (f"s{i}.jpg", data, "image/jpeg")) for i, data in enumerate(images)]
    data = {k: [str(x) for x in v] if isinstance(v, list) else str(v) for k, v in fields.items()}
    return client.post("/api/match", files=files, data=data)


def test_match_requires_selfie(client):
    r = client.post("/api/match", data={"threshold": "0.4"}, files={"other": ("x.txt", b"x", "text/plain")})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "NO_SELFIES"


def test_match_too_many_selfies(client, faces_bgr):
    img = to_jpeg(faces_bgr["lena"])
    r = _post_match(client, [img] * 4)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "TOO_MANY_SELFIES"


def test_match_error_codes_per_selfie(client, faces_bgr):
    noise = np.random.default_rng(1).integers(0, 255, (500, 500, 3), dtype=np.uint8)
    group = np.hstack([cv2.resize(faces_bgr["astronaut"], (512, 512)), cv2.resize(faces_bgr["lena"], (512, 512))])
    blurry = cv2.GaussianBlur(faces_bgr["lena"], (0, 0), 3)
    r = _post_match(client, [to_jpeg(noise), to_jpeg(group), to_jpeg(blurry)])
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "SELFIE_REJECTED"
    codes = {e["index"]: e["code"] for e in detail["errors"]}
    assert codes == {0: "NO_FACE", 1: "MULTIPLE_FACES", 2: "TOO_BLURRY"}
    assert all(e["message"] for e in detail["errors"])


def test_match_invalid_image(client):
    r = _post_match(client, [b"this is not an image at all"])
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["code"] == "INVALID_IMAGE"


def test_match_rejects_fake_extension(client):
    # A text file named .jpg must be rejected by content sniffing.
    r = client.post("/api/match", files=[("selfies", ("me.jpg", b"GIF89a....", "image/jpeg"))])
    assert r.json()["detail"]["errors"][0]["code"] == "INVALID_IMAGE"


def test_match_selfie_too_large(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "MAX_SELFIE_BYTES", 1000)
    r = _post_match(client, [b"\xff\xd8\xff" + b"0" * 5000])
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["code"] == "FILE_TOO_LARGE"


@pytest.mark.parametrize(
    "fields",
    [{"threshold": "0.9"}, {"threshold": "abc"}, {"limit": "0"}, {"offset": "-1"}, {"event_types": "Party"},
     {"event_ids": "not-a-uuid"}],
)
def test_match_invalid_params(client, faces_bgr, fields):
    r = _post_match(client, [to_jpeg(faces_bgr["lena"])], **fields)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_PARAMS"


def test_selfies_never_written_to_disk(client, faces_bgr, monkeypatch):
    """Selfies > 1 MB would be spooled to disk by Starlette's parser; ours must not."""
    import starlette.formparsers

    def forbidden(*_a, **_k):
        raise AssertionError("selfie written to a temporary file")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "TemporaryFile", forbidden)
    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", forbidden)

    import app.api.public.match as match_module
    from app.services.matching import build_response

    seen = {}

    def fake_query(embeddings, *_args):
        seen["n"] = len(embeddings)
        return build_response([], limit=60, offset=0)

    monkeypatch.setattr(match_module, "_run_query", fake_query)

    big = cv2.resize(faces_bgr["lena"], (2400, 2400), interpolation=cv2.INTER_CUBIC)
    payload = to_jpeg(big, quality=100)
    assert len(payload) > 1024 * 1024
    r = _post_match(client, [payload])
    assert r.status_code == 200, r.text
    assert seen["n"] == 1


def test_rate_limit_match(client, faces_bgr, monkeypatch):
    from app.config import get_settings
    from app.ratelimit import limiter

    s = get_settings()
    monkeypatch.setattr(s, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(s, "MATCH_RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(limiter, "_mem", {})
    # Force the in-memory fallback so the test doesn't depend on Redis.
    import app.ratelimit as rl

    monkeypatch.setattr(rl, "get_redis", lambda: (_ for _ in ()).throw(ConnectionError()))
    statuses = [_post_match(client, [b"nope"]).status_code for _ in range(3)]
    assert statuses[:2] == [422, 422]
    assert statuses[2] == 429


# ---------------------------------------------------------------------------
# Database required (TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_token(client, db):
    from app.models import Admin
    from app.security import hash_password

    db.add(Admin(email="admin@example.com", password_hash=hash_password("correct horse battery")))
    db.commit()
    r = client.post("/api/admin/login", json={"email": "Admin@Example.com", "password": "correct horse battery"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_login_wrong_password(client, db, admin_token):
    r = client.post("/api/admin/login", json={"email": "admin@example.com", "password": "wrong"})
    assert r.status_code == 401
    r = client.post("/api/admin/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert r.status_code == 401


def test_event_crud(client, db, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = client.post(
        "/api/admin/events",
        json={"name": "Annual Day", "type": "Cultural", "event_date": "2025-12-01", "description": "Fun"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    ev = r.json()
    assert ev["is_published"] is False

    assert client.get("/api/events").json() == []  # unpublished = invisible

    r = client.put(f"/api/admin/events/{ev['id']}", json={"is_published": True}, headers=h)
    assert r.status_code == 200 and r.json()["is_published"] is True
    pub = client.get("/api/events").json()
    assert [e["name"] for e in pub] == ["Annual Day"]
    assert client.get("/api/event-types").json() == {"types": ["Cultural"]}

    r = client.put(f"/api/admin/events/{ev['id']}", json={"type": "Party"}, headers=h)
    assert r.status_code == 422

    r = client.get(f"/api/admin/events/{ev['id']}/status", headers=h)
    assert r.json() == {"total": 0, "queued": 0, "processing": 0, "done": 0, "failed": 0, "faces": 0}

    assert client.delete(f"/api/admin/events/{ev['id']}", headers=h).status_code == 204
    assert client.get(f"/api/admin/events/{ev['id']}", headers=h).status_code == 404


@pytest.fixture
def seeded(db, engine, faces_bgr):
    """Three events with photos whose faces are real SFace embeddings.

    astronaut appears in: E_new (Sports, 1 photo), E_old (Conference, 2 photos),
    E_hidden (unpublished, 1 photo). lena appears in E_old (1 photo).
    """
    from app.models import Event, Face, Photo

    def emb(img):
        return engine.embed(img, engine.detect(img)[0]).tolist()

    astro, lena = faces_bgr["astronaut"], faces_bgr["lena"]
    variants = [astro, augment(astro), augment(astro, flip=False, angle=-6, alpha=0.95, beta=-5)]

    e_new = Event(name="Sports Day", type="Sports", event_date=date(2025, 9, 1), is_published=True)
    e_old = Event(name="Tech Summit", type="Conference", event_date=date(2025, 3, 1), is_published=True)
    e_hidden = Event(name="Secret Offsite", type="Team Outing", event_date=date(2025, 10, 1), is_published=False)
    db.add_all([e_new, e_old, e_hidden])
    db.flush()

    def add_photo(event, img):
        p = Photo(
            event_id=event.id,
            original_filename="x.jpg",
            file_hash=uuid.uuid4().hex,
            full_path=f"{event.id}/full/x.jpg",
            thumb_path=f"{event.id}/thumb/x.jpg",
            width=1600,
            height=1200,
            face_count=1,
            status="done",
        )
        db.add(p)
        db.flush()
        db.add(Face(photo_id=p.id, event_id=event.id, embedding=emb(img), box={"x": 0, "y": 0, "w": 1, "h": 1}, score=0.9))
        return p

    add_photo(e_new, variants[1])
    add_photo(e_old, variants[2])
    add_photo(e_old, variants[0])
    add_photo(e_old, lena)
    add_photo(e_hidden, variants[0])
    db.commit()
    return {"new": e_new, "old": e_old, "hidden": e_hidden}


def test_match_finds_person_across_published_events(client, seeded, faces_bgr):
    selfie = to_jpeg(augment(faces_bgr["astronaut"], angle=3, scale=0.95))
    r = _post_match(client, [selfie])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3  # not the lena photo, not the unpublished event
    assert [(e["name"], e["count"]) for e in body["by_event"]] == [("Sports Day", 1), ("Tech Summit", 2)]
    assert [p["event_id"] for p in body["photos"]][0] == str(seeded["new"].id)  # newest event first
    sims = [p["similarity"] for p in body["photos"] if p["event_id"] == str(seeded["old"].id)]
    assert sims == sorted(sims, reverse=True)
    assert all(p["similarity"] >= 0.363 for p in body["photos"])
    assert all("embedding" not in p and "box" not in p for p in body["photos"])


def test_match_filters(client, seeded, faces_bgr):
    selfie = to_jpeg(faces_bgr["astronaut"])
    by_type = _post_match(client, [selfie], event_types=["Conference"]).json()
    assert by_type["total"] == 2
    by_id = _post_match(client, [selfie], event_ids=[str(seeded["new"].id)]).json()
    assert by_id["total"] == 1
    hidden = _post_match(client, [selfie], event_ids=[str(seeded["hidden"].id)]).json()
    assert hidden["total"] == 0
    both = _post_match(client, [selfie], event_ids=[str(seeded["new"].id)], event_types=["Conference"]).json()
    assert both["total"] == 0


def test_match_pagination(client, seeded, faces_bgr):
    selfie = to_jpeg(faces_bgr["astronaut"])
    full = _post_match(client, [selfie]).json()
    ids = [p["id"] for p in full["photos"]]
    pages = [_post_match(client, [selfie], limit=1, offset=i).json() for i in range(4)]
    assert [len(p["photos"]) for p in pages] == [1, 1, 1, 0]
    assert [p["photos"][0]["id"] for p in pages[:3]] == ids
    assert all(p["total"] == 3 for p in pages)


def test_match_multiple_selfies_merge(client, seeded, faces_bgr):
    """Two selfies of different people: union of matches, one entry per photo."""
    r = _post_match(client, [to_jpeg(faces_bgr["astronaut"]), to_jpeg(faces_bgr["lena"])])
    body = r.json()
    assert body["total"] == 4
    assert len({p["id"] for p in body["photos"]}) == 4


def test_download_only_published(client, seeded, db):
    from sqlalchemy import select

    from app.models import Photo

    hidden_photo = db.scalar(select(Photo).where(Photo.event_id == seeded["hidden"].id))
    assert client.get(f"/api/photos/{hidden_photo.id}/download").status_code == 404
