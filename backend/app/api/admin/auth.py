"""Admin login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Admin
from app.ratelimit import rate_limit
from app.schemas import LoginRequest, TokenOut
from app.security import create_access_token, verify_password

router = APIRouter(tags=["admin: auth"])


@router.post(
    "/login",
    response_model=TokenOut,
    dependencies=[Depends(rate_limit("login", "LOGIN_RATE_LIMIT_PER_MIN"))],
    summary="Exchange admin username + password for a JWT (5/min per IP)",
)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    admin = db.scalar(select(Admin).where(Admin.email == body.email))
    # verify_password runs bcrypt even for unknown emails (timing equalisation).
    if not verify_password(body.password, admin.password_hash if admin else None) or admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid username or password"},
        )
    token, expires_in = create_access_token(admin.id, admin.email)
    return TokenOut(access_token=token, expires_in=expires_in, email=admin.email)
