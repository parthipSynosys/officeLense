from fastapi import APIRouter

from app.api.admin import auth, events, photos, stats

router = APIRouter(prefix="/admin")
router.include_router(auth.router)
router.include_router(stats.router)
router.include_router(events.router)
router.include_router(photos.router)

__all__ = ["router"]
