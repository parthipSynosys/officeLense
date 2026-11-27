# EventLens — self-hosted event photo finder

Admins upload event photos. Guests take a selfie and instantly see every photo
they appear in, with filters by event and event type, and can view or download
them (single photos or ZIP).

* **100% self-hosted, free and open-source.** No paid or third-party AI APIs.
* **Commercial-use safe.** Face models are OpenCV Zoo **YuNet** (detection) and
  **SFace** (recognition), both Apache-2.0. InsightFace models are *not* used
  (their pretrained weights are non-commercial).
* **Privacy by design.** Selfies are processed in memory only and never stored,
  cached or logged. Face embeddings are never exposed by any public endpoint.
* **Scale.** Built and benchmarked for 20,000+ photos / 100,000+ faces.

```
 Browser (React SPA)                       Ubuntu server
 ───────────────────        ┌──────────────────────────────────────────────┐
  Guest: selfie ──HTTPS──►  │ nginx ── /            → frontend build        │
  Admin: upload             │       ── /photos/     → PHOTOS_DIR (static)   │
                            │       ── /api/        → Gunicorn + FastAPI    │
                            │                          │   (YuNet + SFace)  │
                            │   PostgreSQL 16 ◄────────┤                    │
                            │   + pgvector             ▼                    │
                            │                       Redis ◄── RQ workers    │
                            │                              (index photos)   │
                            └──────────────────────────────────────────────┘
```

## Contents

1. [Server requirements](#1-server-requirements)
2. [Repository layout](#2-repository-layout)
3. [Setup on Ubuntu — Docker](#3-setup-on-ubuntu--docker-recommended)
4. [Setup on Ubuntu — without Docker](#4-setup-on-ubuntu--without-docker)
5. [Frontend build, nginx and HTTPS](#5-frontend-build-nginx-and-https)
6. [Using EventLens](#6-using-eventlens)
7. [API reference with curl examples](#7-api-reference-with-curl-examples)
8. [Threshold tuning guide](#8-threshold-tuning-guide)
9. [Performance: indexing speed and search speed](#9-performance)
10. [Bulk-indexing photos already on the server (overnight)](#10-bulk-indexing-photos-already-on-the-server)
11. [Backup and restore](#11-backup-and-restore)
12. [Privacy notes](#12-privacy-notes)
13. [Configuration reference](#13-configuration-reference)
14. [Development and tests](#14-development-and-tests)
15. [Troubleshooting](#15-troubleshooting)
16. [Licenses](#16-licenses)

---

## 1. Server requirements

| | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 4+ vCPU (indexing speed scales with cores) |
| RAM | 4 GB | 8 GB |
| OS | Ubuntu 22.04 | **Ubuntu 24.04 LTS** |
| Disk | see below | SSD |

**Disk estimate**

* Resized copies (1600px "full" + 400px "thumb"): **about 300 KB per photo**.
  20,000 photos ≈ **6 GB**.
* With `KEEP_ORIGINALS=true`, add the original file sizes (phone/DSLR photos are
  typically 3–10 MB each, so 20,000 photos ≈ 60–200 GB extra).
* PostgreSQL: about **100–150 MB per 100,000 faces**, including the vector index.

You also need a domain (e.g. `photos.example.com`) whose DNS A/AAAA record
points to the server, and ports 80 and 443 open.

---

## 2. Repository layout

```
backend/
  app/
    main.py              FastAPI app (OpenAPI docs at /api/docs)
    config.py            settings from .env
    db/, models/         SQLAlchemy 2.0 models (admins, events, photos, faces)
    schemas/             Pydantic v2 request/response models
    api/admin/           JWT-protected admin endpoints
    api/public/          public endpoints (+ in-memory selfie parser)
    face/engine.py       the single face module: YuNet detect + SFace embed + selfie checks
    services/            images, storage, indexing pipeline, matching
    workers/             RQ queue helpers + multi-process worker launcher
    cli.py               create-admin, bulk-index
  alembic/               database migrations
  models/                ONNX model files (git-ignored, downloaded by script)
  scripts/download_models.py   download + verify the models
  scripts/benchmark_match.py   search benchmark at 100k+ faces
  tests/                 pytest suite
frontend/                React + Vite + TypeScript + Tailwind SPA
deploy/
  docker-compose.yml     api, worker, postgres (pgvector/pgvector:pg16), redis
  nginx.conf             site config (SPA, /photos/ cache, /api proxy, gzip)
  security-headers.conf  nginx snippet (CSP, HSTS, ...)
  systemd/               unit files for the non-Docker setup
```

---

## 3. Setup on Ubuntu — Docker (recommended)

All commands assume you install to `/opt/eventlens`. Replace
`photos.example.com` with your domain.

### 3.1 Install Docker, nginx and certbot

```bash
sudo apt update
sudo apt install -y ca-certificates curl git nginx certbot python3-certbot-nginx
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out and back in afterwards
```

### 3.2 Get the code and configure

```bash
sudo mkdir -p /opt/eventlens && sudo chown $USER: /opt/eventlens
git clone <your-repo-url> /opt/eventlens
cd /opt/eventlens

# Backend settings
cp backend/.env.example backend/.env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # copy into JWT_SECRET
nano backend/.env          # set JWT_SECRET, CORS_ORIGIN=https://photos.example.com, WORKER_CONCURRENCY

# Compose settings
cp deploy/.env.example deploy/.env
nano deploy/.env           # set a strong POSTGRES_PASSWORD
```

In Docker, `DATABASE_URL`, `REDIS_URL`, `PHOTOS_DIR` and `MODELS_DIR` are set by
`docker-compose.yml`, so you don't need to edit them in `backend/.env`.

### 3.3 Create the photo directories

The containers run as uid 1000; nginx (www-data) needs read access.

```bash
sudo mkdir -p /srv/eventlens/photos /srv/eventlens/import
sudo chown -R 1000:1000 /srv/eventlens/photos
sudo chmod 755 /srv/eventlens /srv/eventlens/photos
```

### 3.4 Start the stack

```bash
cd /opt/eventlens/deploy
docker compose up -d --build
```

The image build downloads and verifies the two ONNX models (pinned SHA-256).
The `api` container runs `alembic upgrade head` on every start, so migrations
apply automatically.

```bash
docker compose ps
curl -s http://127.0.0.1:8000/api/health
# {"status":"ok","models_loaded":true,"db_ok":true,"redis_ok":true,"queue_size":0}
```

### 3.5 Create the first admin

```bash
docker compose exec api python -m app.cli create-admin --email admin@example.com
# prompts for the password (min 10 characters)
```

Next, build the frontend and set up nginx and HTTPS: see [section 5](#5-frontend-build-nginx-and-https).

**Updating later:** `git pull && cd deploy && docker compose up -d --build`, then rebuild the frontend.

---

## 4. Setup on Ubuntu — without Docker

These steps target Ubuntu 24.04 (Python 3.12 and PostgreSQL 16 are the defaults).
On 22.04, install Python 3.11+ from the deadsnakes PPA and PostgreSQL 16 from
the official PGDG apt repository.

### 4.1 System packages

```bash
sudo apt update
sudo apt install -y git python3.12-venv python3-dev build-essential \
  postgresql-16 postgresql-16-pgvector redis-server nginx certbot python3-certbot-nginx
sudo systemctl enable --now postgresql redis-server
```

If `postgresql-16-pgvector` isn't found, add the PGDG repository
(https://www.postgresql.org/download/linux/ubuntu/) and install it from there.

### 4.2 Database

```bash
sudo -u postgres psql <<'SQL'
CREATE USER eventlens WITH PASSWORD 'CHANGE_ME_DB_PASSWORD';
CREATE DATABASE eventlens OWNER eventlens;
\c eventlens
CREATE EXTENSION IF NOT EXISTS vector;   -- needs superuser, so do it here
SQL
```

### 4.3 Application user, code and Python environment

```bash
sudo useradd --system --create-home --home-dir /opt/eventlens --shell /usr/sbin/nologin eventlens
sudo mkdir -p /srv/eventlens/photos
sudo chown -R eventlens:eventlens /srv/eventlens
sudo chmod 755 /srv/eventlens /srv/eventlens/photos

sudo -u eventlens git clone <your-repo-url> /opt/eventlens/app-src   # or copy the files
sudo -u eventlens mv /opt/eventlens/app-src/* /opt/eventlens/ && sudo rm -rf /opt/eventlens/app-src

cd /opt/eventlens/backend
sudo -u eventlens python3.12 -m venv .venv
sudo -u eventlens .venv/bin/pip install --upgrade pip
sudo -u eventlens .venv/bin/pip install -r requirements.txt
```

### 4.4 Configure, download models, migrate, create admin

```bash
cd /opt/eventlens/backend
sudo -u eventlens cp .env.example .env
sudo -u eventlens nano .env
#   DATABASE_URL=postgresql+psycopg://eventlens:CHANGE_ME_DB_PASSWORD@localhost:5432/eventlens
#   REDIS_URL=redis://localhost:6379/0
#   PHOTOS_DIR=/srv/eventlens/photos
#   JWT_SECRET=<python3 -c "import secrets; print(secrets.token_urlsafe(48))">
#   CORS_ORIGIN=https://photos.example.com
sudo chmod 600 .env

sudo -u eventlens .venv/bin/python scripts/download_models.py
sudo -u eventlens .venv/bin/alembic upgrade head
sudo -u eventlens .venv/bin/python -m app.cli create-admin --email admin@example.com
```

### 4.5 systemd services

```bash
sudo cp /opt/eventlens/deploy/systemd/eventlens-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eventlens-api eventlens-worker
systemctl status eventlens-api eventlens-worker
curl -s http://127.0.0.1:8000/api/health
```

Logs: `journalctl -u eventlens-api -f` and `journalctl -u eventlens-worker -f`.

**Updating later:** `git pull`, `.venv/bin/pip install -r requirements.txt`,
`.venv/bin/alembic upgrade head`, `sudo systemctl restart eventlens-api eventlens-worker`, then rebuild the frontend.

---

## 5. Frontend build, nginx and HTTPS

### 5.1 Build the frontend

The frontend needs Node.js 18.18+ (20 LTS recommended) **only to build**. The
result is static files.

With Docker (nothing to install on the host):

```bash
cd /opt/eventlens/frontend
docker run --rm -v "$PWD":/app -w /app node:20-alpine sh -c "npm ci && npm run build"
```

Or with Node installed locally (e.g. `sudo apt install nodejs npm` on 24.04, or NodeSource):

```bash
cd /opt/eventlens/frontend
npm ci
npm run build
```

Publish the build:

```bash
sudo mkdir -p /var/www/eventlens
sudo rsync -a --delete dist/ /var/www/eventlens/
```

### 5.2 HTTPS certificate (certbot)

Get the certificate **before** enabling the EventLens site, because the site
config references the certificate files. Let's Encrypt is free.

```bash
sudo certbot certonly --nginx -d photos.example.com --agree-tos -m you@example.com
```

Renewal is automatic (`systemctl list-timers | grep certbot`). Test it with
`sudo certbot renew --dry-run`.

### 5.3 nginx

```bash
sudo cp /opt/eventlens/deploy/security-headers.conf /etc/nginx/snippets/eventlens-security-headers.conf
sudo cp /opt/eventlens/deploy/nginx.conf /etc/nginx/sites-available/eventlens
sudo sed -i 's/photos.example.com/YOUR.DOMAIN/g' /etc/nginx/sites-available/eventlens
sudo ln -s /etc/nginx/sites-available/eventlens /etc/nginx/sites-enabled/eventlens
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

What the config does:

* serves the SPA from `/var/www/eventlens` with an `index.html` fallback;
  hashed `/assets/` are cached for a year, `index.html` is never cached
* serves `/photos/` straight from `/srv/eventlens/photos` with a 30-day
  immutable cache (file names are UUIDs); `_incoming/` and `original/` are blocked
* proxies `/api/` to `127.0.0.1:8000`, overwriting `X-Forwarded-For` so rate
  limits see the real client IP
* `/api/match`: 26 MB body limit and a body buffer of the same size, so **nginx
  never writes selfies to its temp files on disk**
* `/api/admin/`: 200 MB body limit with request buffering off (streams batch uploads)
* gzip, HSTS, CSP, `Permissions-Policy: camera=(self)`, etc.

Open `https://photos.example.com` (guests) and `https://photos.example.com/admin` (admins).

> The selfie camera only works over **HTTPS** (browsers block `getUserMedia` on
> plain HTTP). On HTTP, guests can still use "Upload a selfie".

---

## 6. Using EventLens

**Admins** (`/admin`)

1. **Events → New event**: name, type (Conference, Workshop, Cultural, Sports,
   Award Ceremony, Team Outing, Other), date and description.
2. Open the event and **drag and drop photos or whole folders**. Files are sent
   in small batches, so one failure doesn't stop the rest, and failed batches can
   be retried. Duplicates (same file content within the event) are skipped.
3. Watch **live indexing progress** (queued / processing / done / failed, faces
   found). Failed photos show the error and can be retried. **Re-index event**
   re-runs face detection for every photo.
4. Hover a photo and click ★ to make it the **cover**, then switch on **Published**.
   Unpublished events are invisible to guests and to search.

**Guests** (`/`)

1. Optionally filter by event type or by specific events, then tick the consent box.
2. Take a selfie with the front camera (or upload one). Adding a second or third
   selfie from another angle finds more photos.
3. See "We found N photos of you", browse per event, open the lightbox (swipe on
   mobile), download single photos, the whole event, or everything as a ZIP.
4. "Show more possible matches" re-runs the search at a lower threshold (0.30).
   "Start over" clears the selfies from memory.

---

## 7. API reference with curl examples

Interactive OpenAPI docs: **`https://photos.example.com/api/docs`**.
Errors share one shape: `{"detail": {"code": "...", "message": "...", ...}}`.

```bash
API=https://photos.example.com/api
```

### Admin

```bash
# Log in (5/min per IP) -> JWT (HS256), valid JWT_EXPIRE_MINUTES (default 8 h)
TOKEN=$(curl -s -X POST $API/admin/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"..."}' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

curl -s $API/admin/stats -H "$AUTH"
# {"events":3,"published_events":2,"photos":5120,"faces":21877,"failed":2,"processing":4,"queue":130}

# Create / list / update / delete events
curl -s -X POST $API/admin/events -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Annual Day 2025","type":"Cultural","event_date":"2025-12-12","description":"","is_published":false}'
curl -s $API/admin/events -H "$AUTH"
curl -s -X PUT $API/admin/events/$EVENT -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"is_published":true,"cover_photo_id":"<photo uuid>"}'      # partial update; "cover_photo_id":null clears
curl -s -X DELETE $API/admin/events/$EVENT -H "$AUTH"                # permanently removes photos, files and faces

# Upload photos and videos (multipart field "files", many at once; photos max 30 MB,
# videos — MP4, MOV, WebM, MKV, AVI — max 500 MB, sampled ~1 frame/s for faces)
curl -s -X POST $API/admin/events/$EVENT/photos -H "$AUTH" \
  -F files=@IMG_0001.jpg -F files=@IMG_0002.HEIC -F files=@speech.mp4
# {"accepted":[{"id":"...","filename":"IMG_0001.jpg"}, ...],"duplicates":[],"rejected":[]}

curl -s "$API/admin/events/$EVENT/photos?page=1&page_size=60&status=failed" -H "$AUTH"
curl -s $API/admin/events/$EVENT/status -H "$AUTH"
# {"total":420,"queued":12,"processing":3,"done":400,"failed":5,"faces":1893}
curl -s -X POST $API/admin/events/$EVENT/retry-failed -H "$AUTH"    # {"queued":5}
curl -s -X POST $API/admin/events/$EVENT/reindex -H "$AUTH"         # {"queued":420}
curl -s -X DELETE $API/admin/photos/$PHOTO -H "$AUTH"
```

### Public

```bash
curl -s $API/events
# [{"id":"...","name":"Annual Day 2025","type":"Cultural","date":"2025-12-12","cover_thumb_url":"/photos/...","photo_count":412}]

curl -s $API/event-types            # {"types":["Conference","Cultural"]}

# Match: 1–3 selfies (max 8 MB each), optional filters (10/min per IP)
curl -s -X POST $API/match \
  -F selfies=@me.jpg -F selfies=@me2.jpg \
  -F event_types=Cultural -F event_ids=$EVENT \
  -F threshold=0.363 -F limit=60 -F offset=0
# {"total":27,
#  "by_event":[{"event_id":"...","name":"Annual Day 2025","type":"Cultural","event_date":"2025-12-12","count":12}, ...],
#  "photos":[{"id":"...","event_id":"...","thumb_url":"/photos/<event>/thumb/<id>.jpg",
#             "full_url":"/photos/<event>/full/<id>.jpg","width":1600,"height":1067,"similarity":0.6123}, ...],
#  "limit":60,"offset":0}
# Sorted by event_date desc, then similarity desc.

# A rejected selfie -> 422 with per-selfie codes:
# {"detail":{"code":"SELFIE_REJECTED","message":"...","errors":[{"index":0,"code":"NO_FACE","message":"..."}]}}
# Codes: INVALID_IMAGE, FILE_TOO_LARGE, NO_FACE, MULTIPLE_FACES, FACE_TOO_SMALL, TOO_BLURRY, TOO_DARK, TOO_BRIGHT
# Other 422 codes: NO_SELFIES, TOO_MANY_SELFIES, INVALID_PARAMS.  429 = RATE_LIMITED.

curl -OJ $API/photos/$PHOTO/download   # full image as attachment (published events only)
curl -s $API/health                    # 200 when models, DB and Redis are OK; 503 otherwise
```

---

## 8. Threshold tuning guide

Matching compares the selfie embedding with every face using **cosine
similarity** (1.0 = identical). A photo matches when its similarity is at least
`MATCH_THRESHOLD`.

* **Default 0.363** is OpenCV's recommended SFace threshold, a good balance.
* Allowed range is **0.30 – 0.45**.

| Symptom | Action |
|---|---|
| **Wrong people** appear in results | **Raise** the threshold: try 0.38, then 0.40, then 0.42 |
| Guests say **photos are missing** | **Lower** it: try 0.34, then 0.32. Guests can also click "Show more possible matches" (0.30) and add 2–3 selfies |
| Twins / very similar colleagues | Raise it to 0.40+ and ask guests for multiple selfies |

How to tune:

1. Choose 3–5 volunteers whose photos you know well.
2. For each, run a search (UI or `curl … -F threshold=0.34`, then 0.36, 0.38, 0.40)
   and count correct results versus wrong ones. Each photo's `similarity` is in the response.
3. Pick the lowest threshold that shows no wrong people, set `MATCH_THRESHOLD`
   in `.env`, and restart the API (`docker compose restart api` or
   `systemctl restart eventlens-api`).

Changing the threshold needs **no re-indexing**: it only affects search.
Re-index only if you change detection settings or upgrade the models.

---

## 9. Performance

### Indexing speed

Measured on the development machine (8-core laptop CPU, one worker process,
OpenCV limited to one thread). A 12-megapixel JPEG with 6 faces takes
**about 0.7 s**: decode, EXIF rotate, resize, save two JPEGs, detect and embed.
Small photos take under 0.2 s. Server CPUs vary, so use these as a guide:

| Server | Workers | Throughput (12 MP) | 20,000 photos |
|---|---|---|---|
| 2 vCPU | 1 | ~1.2–1.5 photos/s | ~4–5 h |
| 4 vCPU | 3 | ~3.5–4 photos/s | ~1.5 h |
| 8 vCPU | 7 | ~8–9 photos/s | ~40 min |

`WORKER_CONCURRENCY` (default: cores − 1) sets the number of worker
processes. Each one uses about 300–500 MB RAM while processing large photos.

### Search speed (`/api/match`)

`/api/match` runs an **exact** (non-approximate) cosine scan with pgvector over
the faces of published events, with event and type filters applied in the same
query. Exact search guarantees filtered results are complete; an approximate
HNSW scan followed by a filter can silently drop matches. The HNSW index exists
for future unfiltered top-k use, but the match query (no `ORDER BY … LIMIT`)
never uses it.

Benchmark (`backend/scripts/benchmark_match.py`, 100,000 random 128-d faces in
50 events, PostgreSQL 16 + pgvector, same dev machine):

| Query | Median | Max |
|---|---|---|
| 1 selfie, all events | **43 ms** | 53 ms |
| 1 selfie, filtered to 20% of events | **8 ms** | 10 ms |
| 3 selfies, all events | **51 ms** | 61 ms |
| 3 selfies, filtered | **10 ms** | 12 ms |

That is far under the 1 s target. Selfie detection and embedding add about
50–150 ms per selfie. Run the benchmark on your own server:

```bash
cd backend && .venv/bin/python scripts/benchmark_match.py --faces 100000 --events 50
# Docker: docker compose exec api python scripts/benchmark_match.py
```

It uses a throw-away schema and doesn't touch your data. As a rule of thumb,
exact scan time grows linearly: about 0.5 s at roughly 1 million faces. Beyond
that, switch the query to HNSW with `SET hnsw.iterative_scan = relaxed_order`
(pgvector ≥ 0.8).

---

## 10. Bulk-indexing photos already on the server

For large archives already on the server (e.g. copied from a camera or NAS),
skip the browser and index them directly:

```bash
# 1. Create the event in the admin UI and copy its id from the URL (/admin/events/<id>)
# 2. Run (non-Docker):
cd /opt/eventlens/backend
sudo -u eventlens .venv/bin/python -m app.cli bulk-index \
  --event 3f1c...-uuid --dir /data/raw/annual-day --workers 3

# Docker: put the photos under /srv/eventlens/import (mounted read-only at /import)
docker compose exec worker python -m app.cli bulk-index --event 3f1c...-uuid --dir /import/annual-day
```

* Scans the folder recursively for `.jpg .jpeg .png .webp .heic .heif`.
* **Resumable**: files already indexed in the event (same SHA-256) are skipped,
  and failed or interrupted ones are retried. Just run the same command again.
* Source files are **copied, never moved or modified**.
* Shows a tqdm progress bar, then prints a summary (photos, faces, time) and
  writes `bulk-index-failed-<timestamp>.txt` listing any failures.

**Overnight runs.** Use `tmux` (or `screen`) so the job survives SSH disconnects:

```bash
tmux new -s bulk
sudo -u eventlens .venv/bin/python -m app.cli bulk-index --event <id> --dir /data/raw/annual-day
# detach: Ctrl-b d      re-attach: tmux attach -t bulk
```

Or as a one-off systemd job with logs in the journal:

```bash
sudo systemd-run --unit=eventlens-bulk --uid=eventlens --nice=10 \
  --working-directory=/opt/eventlens/backend \
  /opt/eventlens/backend/.venv/bin/python -m app.cli bulk-index --event <id> --dir /data/raw/annual-day
journalctl -u eventlens-bulk -f
```

Tip: on a small server, stop the regular workers during a big bulk run
(`systemctl stop eventlens-worker`) and give bulk-index all cores
(`--workers <cores>`).

---

## 11. Backup and restore

Back up two things: the **PostgreSQL database** and **`PHOTOS_DIR`**. The models
can always be downloaded again.

```bash
# Database (Docker)
docker compose -f /opt/eventlens/deploy/docker-compose.yml exec -T postgres \
  pg_dump -U eventlens -Fc eventlens > /backup/eventlens-$(date +%F).dump
# Database (non-Docker)
sudo -u postgres pg_dump -Fc eventlens > /backup/eventlens-$(date +%F).dump

# Photos (incremental)
rsync -a --delete /srv/eventlens/photos/ /backup/photos/
```

Example nightly cron (`sudo crontab -e`):

```cron
30 2 * * * sudo -u postgres pg_dump -Fc eventlens > /backup/eventlens-$(date +\%F).dump && find /backup -name 'eventlens-*.dump' -mtime +14 -delete
0  3 * * * rsync -a --delete /srv/eventlens/photos/ /backup/photos/
```

Copy `/backup` off the server (e.g. `rclone` to another machine or object storage).

**Restore**

```bash
sudo -u postgres createdb -O eventlens eventlens
sudo -u postgres psql -d eventlens -c 'CREATE EXTENSION IF NOT EXISTS vector;'
sudo -u postgres pg_restore -d eventlens --no-owner --role=eventlens /backup/eventlens-2025-12-01.dump
rsync -a /backup/photos/ /srv/eventlens/photos/
```

---

## 12. Privacy notes

* **Consent.** Guests must tick a consent box before taking a selfie. The notice
  reads: "Your selfie is only used to find your photos. It is never saved."
* **Selfies are never stored.** They go from the browser's memory to the API in
  a single request. nginx keeps the request body in RAM (`client_body_buffer_size`).
  The API parses multipart data with a strictly in-memory parser (FastAPI's
  default would spool files over 1 MB to `/tmp`). Each selfie is decoded and
  embedded in memory, then discarded. Nothing about a selfie (bytes, embedding,
  metrics) is written to disk, the database, Redis or the logs. A test
  (`test_selfies_never_written_to_disk`) enforces this. In the browser, selfies
  live only in React state and "Start over" or closing the tab removes them.
* **Embeddings stay private.** Face boxes and embeddings exist only in the
  `faces` table and never appear in any public response. Search results contain
  only photo ids, URLs, sizes and a similarity score.
* **No EXIF leakage.** The resized copies are re-encoded without EXIF
  (GPS, camera serial numbers, …). Originals, if kept, are never served by nginx.
* **Deleting an event** permanently removes its photo rows, face embeddings
  (`ON DELETE CASCADE`) and every file on disk. Deleting a single photo does the
  same for that photo. Backups made earlier still contain the data, so apply
  your retention policy to backups too.
* **Unpublished events** are hidden from the event list, search and downloads.
  Their resized files remain on disk under unguessable UUID paths. Delete an
  event to remove it completely.
* **Security.** Admin auth uses bcrypt password hashes and short-lived HS256
  JWTs. Rate limits: 10/min per IP on `/api/match` and 5/min on login. Uploads
  are validated by real file content (magic bytes plus decoder), not by
  extension. CORS is restricted to `CORS_ORIGIN`.
* Tell your attendees about the photo finder (e.g. on the event invitation) and
  follow your local data-protection rules (GDPR/DPDP etc.). Biometric data is
  sensitive personal data in many jurisdictions.

---

## 13. Configuration reference

All settings live in `backend/.env` (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…/eventlens` | PostgreSQL 16 + pgvector |
| `REDIS_URL` | `redis://localhost:6379/0` | job queue + rate limits |
| `PHOTOS_DIR` | `./data/photos` | where photos are stored |
| `PUBLIC_PHOTOS_URL` | `/photos` | URL prefix nginx serves `PHOTOS_DIR` at |
| `JWT_SECRET` | *(required, ≥ 32 chars)* | admin token signing key |
| `JWT_EXPIRE_MINUTES` | `480` | admin session length |
| `CORS_ORIGIN` | `http://localhost:5173` | allowed origin(s), comma-separated |
| `MATCH_THRESHOLD` | `0.363` | cosine similarity for a match (0.30–0.45) |
| `MAX_SELFIES` | `3` | selfies per search |
| `WORKER_CONCURRENCY` | cores − 1 | indexing processes |
| `KEEP_ORIGINALS` | `false` | keep uploaded originals |
| `MODELS_DIR` | `./models` | ONNX models location |
| `BLUR_THRESHOLD` / `DARK_THRESHOLD` / `BRIGHT_THRESHOLD` | `25` / `45` / `215` | selfie quality checks |
| `RATE_LIMIT_ENABLED` | `true` | per-IP rate limiting |
| `MATCH_RATE_LIMIT_PER_MIN` / `LOGIN_RATE_LIMIT_PER_MIN` | `10` / `5` | limits |

Gunicorn: `WEB_CONCURRENCY` (API worker processes, default 2–4) and
`FORWARDED_ALLOW_IPS` (default `127.0.0.1`).

---

## 14. Development and tests

### Quickest local run (no Docker, no Redis, no PostgreSQL install; works on Windows)

`scripts/dev.py` starts an embedded PostgreSQL 16 + pgvector (`pgserver`, data in
`backend/data/`), indexes photos in background threads (`QUEUE_MODE=inline`) and
serves `/photos` from the API. It needs Python 3.12 (pgserver has no 3.13+ wheels).
Use it for development only.

```powershell
cd backend
py -m pip install uv                      # once
uv venv --python 3.12 .venv               # once (downloads Python 3.12 if needed)
uv pip install --python .venv -r requirements-local.txt
.venv\Scripts\python scripts\dev.py create-admin --email admin@example.com
.venv\Scripts\python scripts\dev.py run   # http://127.0.0.1:8000/api/docs
```

### Full local setup

```bash
# Backend (Linux/macOS/WSL; the RQ worker needs a POSIX OS)
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/download_models.py
cp .env.example .env     # point DATABASE_URL / REDIS_URL at local services, set JWT_SECRET
alembic upgrade head
python -m app.cli create-admin --email dev@example.com
uvicorn app.main:app --reload          # API on :8000, docs at /api/docs
python -m app.workers.run              # in another terminal

# Frontend (Vite proxies /api and /photos to :8000)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

A quick local Postgres + Redis:
`docker run -d -p 5432:5432 -e POSTGRES_USER=eventlens -e POSTGRES_PASSWORD=eventlens -e POSTGRES_DB=eventlens pgvector/pgvector:pg16`
and `docker run -d -p 6379:6379 valkey/valkey:8-alpine`.

### Tests

```bash
cd backend
pytest                                   # engine, matching and API tests that need no DB
TEST_DATABASE_URL=postgresql+psycopg://eventlens:eventlens@localhost:5432/eventlens_test pytest
```

* `test_engine.py`: detects faces in sample images; rejects no-face,
  multi-face, small, blurry, dark and bright selfies; embeddings are 128-d and
  L2-normalised.
* `test_matching.py`: same person scores above the threshold, a different
  person below it; best-similarity merge; sorting; pagination.
* `test_api.py`: auth required on every admin route; `/match` error codes;
  parameter validation; selfies never touch disk; rate limiting; with a DB,
  filters, pagination, multi-selfie merge and CRUD.
* `test_indexing.py` (DB): upload → index → match → cover → re-index → delete,
  failed-photo retry, `KEEP_ORIGINALS`, resumable bulk-index.

Sample face images download automatically into `tests/.data/` on first run.
`TEST_DATABASE_URL` **must** point to a database the tests may wipe. Tests never
read `DATABASE_URL` from `.env`.

---

## 15. Troubleshooting

| Problem | Fix |
|---|---|
| `/api/health` shows `models_loaded:false` | Run `python scripts/download_models.py` (Docker images include the models) |
| `redis_ok:false`, photos stuck "queued" | Start Redis, then click **Retry failed** (photos that couldn't be queued are marked failed) |
| Photos stay "queued" | Check that the worker runs: `systemctl status eventlens-worker` / `docker compose logs worker` |
| Camera doesn't open | The site must be served over HTTPS. Check browser camera permissions. Guests can use "Upload a selfie" |
| 413 on upload | The nginx `client_max_body_size` for `/api/admin/` is too small for your batch |
| Images 404 under `/photos/` | Check the `alias` path in nginx and that www-data can read `PHOTOS_DIR` (`chmod 755` dirs) |
| Everyone shares one rate limit | `X-Forwarded-For` isn't reaching the app; check `FORWARDED_ALLOW_IPS` and the nginx `proxy_set_header` lines |
| `CREATE EXTENSION vector` permission denied | Create the extension as the `postgres` superuser (section 4.2) |

---

## 16. Licenses

| Component | License |
|---|---|
| YuNet / SFace models (OpenCV Zoo) | Apache-2.0 |
| OpenCV, NumPy, FastAPI, Starlette, Pydantic, SQLAlchemy, Alembic | Apache-2.0 / BSD / MIT |
| PostgreSQL, pgvector | PostgreSQL License |
| Valkey 8 (Docker job queue) / Ubuntu's `redis-server` 7.0 (non-Docker) | BSD-3 (Redis ≥ 7.4 is no longer OSI-licensed, so it isn't used; on other distros install `valkey`) |
| RQ, redis-py, psycopg | BSD / LGPL-3.0 (psycopg, used as an unmodified library) |
| Pillow, pillow-heif | HPND / BSD-3 (pillow-heif bundles libheif, LGPL-3.0, dynamically linked) |
| React, Vite, Tailwind CSS, JSZip, Inter font | MIT / MIT / MIT / MIT (or GPLv3, dual) / OFL-1.1 |
