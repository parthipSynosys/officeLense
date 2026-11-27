#!/usr/bin/env python3
"""Run the EventLens backend locally WITHOUT Docker, Redis or a PostgreSQL install.

Works on Windows, macOS and Linux. Uses:
  * pgserver  — an embedded PostgreSQL 16 + pgvector, data in backend/data/pg
  * QUEUE_MODE=inline — photos are indexed in background threads of the API
  * SERVE_PHOTOS=true — the API serves /photos itself (no nginx)

    python scripts/dev.py run [--port 8000]          start the API (Ctrl+C to stop)
    python scripts/dev.py create-admin --email you@example.com

FOR LOCAL DEVELOPMENT / TRYING IT OUT ONLY. Production uses deploy/ (Docker or
systemd) with a real PostgreSQL, Redis and worker processes.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DATA = BACKEND / "data"


def _dev_secret() -> str:
    """A JWT secret persisted in backend/data so logins survive restarts."""
    f = DATA / "dev_jwt_secret"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


def start_database():
    """Start (or reuse) the embedded PostgreSQL and make sure the database exists."""
    try:
        import pgserver
    except ImportError:
        sys.exit("pgserver is not installed. Run:  pip install -r requirements-local.txt")

    DATA.mkdir(parents=True, exist_ok=True)
    print("Starting embedded PostgreSQL (first start takes ~10 s)...", flush=True)
    server = pgserver.get_server(DATA / "pg")  # stops automatically when this process exits
    if "(0 rows)" in server.psql("SELECT 1 FROM pg_database WHERE datname = 'eventlens';"):
        server.psql("CREATE DATABASE eventlens;")
    uri = server.get_uri("eventlens")
    return server, uri.replace("postgresql://", "postgresql+psycopg://", 1)


def configure_env(database_url: str) -> None:
    """Local-mode settings. They override values in backend/.env (env vars win)."""
    os.environ["DATABASE_URL"] = database_url
    os.environ["QUEUE_MODE"] = "inline"
    os.environ["SERVE_PHOTOS"] = "true"
    os.environ.setdefault("PHOTOS_DIR", str(DATA / "photos"))
    os.environ.setdefault("MODELS_DIR", str(BACKEND / "models"))
    os.environ.setdefault("CORS_ORIGIN", "http://localhost:5173")
    if not os.environ.get("JWT_SECRET"):
        os.environ["JWT_SECRET"] = _dev_secret()
    # Default local admin login (admin / 123456) unless backend/.env defines one.
    env_file = BACKEND / ".env"
    defined = env_file.is_file() and "ADMIN_USERNAME=" in env_file.read_text(encoding="utf-8")
    if not defined:
        os.environ.setdefault("ADMIN_USERNAME", "admin")
        os.environ.setdefault("ADMIN_PASSWORD", "123456")
    os.chdir(BACKEND)  # alembic.ini + .env are resolved from here
    sys.path.insert(0, str(BACKEND))


def ensure_models() -> None:
    models = BACKEND / "models"
    if not (models / "face_detection_yunet_2023mar.onnx").is_file() or not (
        models / "face_recognition_sface_2021dec.onnx"
    ).is_file():
        print("Downloading face models...", flush=True)
        sys.path.insert(0, str(BACKEND / "scripts"))
        import download_models

        sys.argv = ["download_models.py"]
        if download_models.main() != 0:
            sys.exit("Model download failed.")


def migrate() -> None:
    from alembic.config import main as alembic

    alembic(argv=["-q", "upgrade", "head"])


def cmd_run(args: argparse.Namespace) -> int:
    _server, url = start_database()
    configure_env(url)
    ensure_models()
    migrate()

    import uvicorn

    print(
        f"\n  EventLens API running (local mode)\n"
        f"    API docs : http://127.0.0.1:{args.port}/api/docs\n"
        f"    Health   : http://127.0.0.1:{args.port}/api/health\n"
        f"    Frontend : run `npm run dev` in frontend/ and open http://localhost:5173\n"
        f"  Press Ctrl+C to stop.\n",
        flush=True,
    )
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    _server, url = start_database()
    configure_env(url)
    migrate()
    from app.cli import main as cli

    argv = ["create-admin", "--email", args.email]
    if args.reset:
        argv.append("--reset")
    if args.password_stdin:
        argv.append("--password-stdin")
    return cli(argv)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="start the API with an embedded database")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("create-admin", help="create (or --reset) an admin user")
    p.add_argument("--email", required=True)
    p.add_argument("--reset", action="store_true")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    p.set_defaults(func=cmd_create_admin)
    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
