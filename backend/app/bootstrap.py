"""Startup tasks: ensure the single configured admin account exists."""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import get_settings
from app.db.session import SessionLocal
from app.models import Admin
from app.security import hash_password, verify_password

log = logging.getLogger(__name__)


def ensure_single_admin() -> None:
    """Make ADMIN_USERNAME / ADMIN_PASSWORD the one and only admin.

    Idempotent and safe to run in every Gunicorn worker at the same time.
    """
    s = get_settings()
    username = s.ADMIN_USERNAME.strip().lower()
    if not username or not s.ADMIN_PASSWORD:
        return
    try:
        with SessionLocal() as db:
            removed = db.execute(delete(Admin).where(Admin.email != username)).rowcount
            admin = db.scalar(select(Admin).where(Admin.email == username))
            if admin is None:
                db.add(Admin(email=username, password_hash=hash_password(s.ADMIN_PASSWORD)))
                log.info("Created admin '%s'", username)
            elif not verify_password(s.ADMIN_PASSWORD, admin.password_hash):
                admin.password_hash = hash_password(s.ADMIN_PASSWORD)
                log.info("Updated password for admin '%s'", username)
            if removed:
                log.info("Removed %d other admin account(s)", removed)
            db.commit()
    except IntegrityError:
        pass  # another worker created it at the same moment
    except OperationalError as exc:
        log.error("Could not ensure admin account (database unavailable): %s", exc.__class__.__name__)
