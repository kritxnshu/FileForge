"""All runtime configuration. Every variable is documented in docs/ENV.md."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=True)

    STORAGE_DIR: Path = Path("./data")
    REDIS_URL: str = "redis://localhost:6379/0"
    PUBLIC_BASE_URL: str = "http://localhost:8080"

    MAX_FILE_SIZE_MB: int = 100
    MAX_VIDEO_SIZE_MB: int = 500
    MAX_BATCH_FILES: int = 20
    MAX_BATCH_TOTAL_MB: int = 1000
    MAX_IMAGE_PIXELS: int = 100_000_000

    ARCHIVE_MAX_ENTRIES: int = 10_000
    ARCHIVE_MAX_UNCOMPRESSED_MB: int = 2000
    ARCHIVE_MAX_RATIO: int = 100
    ARCHIVE_MAX_DEPTH: int = 2

    JOB_TIMEOUT_FAST_S: int = 60
    JOB_TIMEOUT_HEAVY_S: int = 900
    JOB_MEMORY_FAST_MB: int = 2048
    JOB_MEMORY_HEAVY_MB: int = 4096
    WORKER_CONCURRENCY_FAST: int = max(2, (os.cpu_count() or 2))
    WORKER_CONCURRENCY_HEAVY: int = max(1, (os.cpu_count() or 2) // 4)

    FILE_RETENTION_MINUTES: int = 60
    SWEEP_INTERVAL_S: int = 60

    RATE_LIMIT_JOBS_PER_10MIN: int = 30
    RATE_LIMIT_UPLOADS_PER_10MIN: int = 60
    RATE_LIMIT_MB_PER_HOUR: int = 2000
    RATE_LIMIT_CONCURRENT_JOBS: int = 10
    TRUSTED_PROXY_HOPS: int = 0

    ENABLE_AGPL_ENGINES: bool = False
    ENABLE_OCR: bool = False
    ENABLE_BACKGROUND_REMOVAL: bool = False
    ENABLE_EXPERIMENTAL: bool = False

    COOKIE_SECURE: bool = True
    LOG_LEVEL: str = "INFO"

    @property
    def retention_s(self) -> int:
        return self.FILE_RETENTION_MINUTES * 60

    def limits_public(self) -> dict:
        return {
            "max_file_size_mb": self.MAX_FILE_SIZE_MB,
            "max_video_size_mb": self.MAX_VIDEO_SIZE_MB,
            "max_batch_files": self.MAX_BATCH_FILES,
            "max_batch_total_mb": self.MAX_BATCH_TOTAL_MB,
            "max_image_megapixels": self.MAX_IMAGE_PIXELS // 1_000_000,
            "retention_minutes": self.FILE_RETENTION_MINUTES,
            "jobs_per_10min": self.RATE_LIMIT_JOBS_PER_10MIN,
        }


@cache
def settings() -> Settings:
    s = Settings()
    s.STORAGE_DIR = s.STORAGE_DIR.resolve()
    # Feature flags are read by the engine registry from the environment.
    for flag in ("ENABLE_AGPL_ENGINES", "ENABLE_OCR", "ENABLE_BACKGROUND_REMOVAL", "ENABLE_EXPERIMENTAL"):
        os.environ.setdefault(flag, "true" if getattr(s, flag) else "false")
    os.environ.setdefault("MAX_IMAGE_PIXELS", str(s.MAX_IMAGE_PIXELS))
    return s
