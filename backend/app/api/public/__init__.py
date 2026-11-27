from fastapi import APIRouter

from app.api.public import events, health, match, photos

router = APIRouter()
router.include_router(events.router)
router.include_router(match.router)
router.include_router(photos.router)
router.include_router(health.router)

__all__ = ["router"]
