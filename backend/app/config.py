"""Application configuration, loaded from environment variables and `.env`.

Every setting can be overridden by an environment variable of the same name.
See `.env.example` for documentation of each value.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hard bounds for the cosine-similarity match threshold (SFace recommends 0.363).
MIN_THRESHOLD = 0.30
MAX_THRESHOLD = 0.45


def _default_concurrency() -> int:
    """Default worker count: CPU cores minus one (always at least 1)."""
    return max(1, (os.cpu_count() or 2) - 1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Infrastructure -------------------------------------------------
    DATABASE_URL: str = "postgresql+psycopg://eventlens:eventlens@localhost:5432/eventlens"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Storage --------------------------------------------------------
    PHOTOS_DIR: Path = Path("./data/photos")
    # URL prefix under which nginx serves PHOTOS_DIR (e.g. "/photos").
    PUBLIC_PHOTOS_URL: str = "/photos"
    KEEP_ORIGINALS: bool = False
    MODELS_DIR: Path = Path("./models")
    # Local development only: let the API serve PHOTOS_DIR at /photos (nginx does this in production).
    SERVE_PHOTOS: bool = False

    # --- Security -------------------------------------------------------
    # The single admin account. When both are set, the API makes sure on startup
    # that exactly this one admin exists (password updated if changed, any other
    # admins removed). Leave empty to manage admins with `python -m app.cli`.
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""
    JWT_SECRET: str = Field(min_length=32)
    JWT_EXPIRE_MINUTES: int = Field(480, ge=5, le=7 * 24 * 60)
    # Comma-separated list of allowed browser origins.
    CORS_ORIGIN: str = "http://localhost:5173"

    # --- Matching -------------------------------------------------------
    MATCH_THRESHOLD: float = Field(0.363, ge=MIN_THRESHOLD, le=MAX_THRESHOLD)
    MAX_SELFIES: int = Field(3, ge=1, le=3)
    MAX_MATCH_LIMIT: int = Field(500, ge=1, le=2000)

    # --- Selfie quality checks -------------------------------------------
    # Laplacian variance of the (normalised) face crop. Lower = blurrier.
    BLUR_THRESHOLD: float = 25.0
    # Mean grey level (0–255) of the face crop.
    DARK_THRESHOLD: float = 45.0
    BRIGHT_THRESHOLD: float = 215.0

    # --- Upload limits (bytes) -------------------------------------------
    MAX_SELFIE_BYTES: int = 8 * 1024 * 1024
    MAX_PHOTO_BYTES: int = 30 * 1024 * 1024
    MAX_VIDEO_BYTES: int = 500 * 1024 * 1024

    # --- Video indexing ----------------------------------------------------
    # Frames sampled per second of video for face detection, and a hard cap on
    # sampled frames (long videos are sampled more sparsely to stay under it).
    VIDEO_SAMPLE_FPS: float = Field(1.0, gt=0, le=10)
    VIDEO_MAX_FRAMES: int = Field(300, ge=1, le=5000)

    # --- Workers ----------------------------------------------------------
    WORKER_CONCURRENCY: int = Field(default_factory=_default_concurrency, ge=1)
    JOB_TIMEOUT_SECONDS: int = 600
    # "rq"     = production: jobs go to Redis and run in `python -m app.workers.run`.
    # "inline" = local development without Redis: jobs run in background threads
    #            inside the API process (also makes rate limiting in-memory).
    QUEUE_MODE: Literal["rq", "inline"] = "rq"

    # --- Rate limiting (requests per minute per IP) -----------------------
    RATE_LIMIT_ENABLED: bool = True
    MATCH_RATE_LIMIT_PER_MIN: int = 10
    LOGIN_RATE_LIMIT_PER_MIN: int = 5

    # --- Misc ---------------------------------------------------------------
    LOAD_MODELS_ON_STARTUP: bool = True
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGIN.split(",") if o.strip()]

    @property
    def yunet_path(self) -> Path:
        return self.MODELS_DIR / "face_detection_yunet_2023mar.onnx"

    @property
    def sface_path(self) -> Path:
        return self.MODELS_DIR / "face_recognition_sface_2021dec.onnx"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()  # type: ignore[call-arg]
