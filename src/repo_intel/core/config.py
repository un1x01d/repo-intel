from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="REPO_INTEL_", extra="ignore", populate_by_name=True)

    db_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/repo_intel",
        alias="DB_URL",
    )
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    worker_checkout_root: str = Field(default="/tmp/repo-intel/checkouts", alias="WORKER_CHECKOUT_ROOT")
    ai_enabled: bool = Field(default=False, alias="AI_ENABLED")
    vertex_project_id: str | None = Field(default=None, alias="VERTEX_PROJECT_ID")
    vertex_location: str = Field(default="us-central1", alias="VERTEX_LOCATION")
    vertex_model: str = Field(default="gemini-2.0-flash-001", alias="VERTEX_MODEL")
    vertex_context_cache_enabled: bool = Field(default=False, alias="VERTEX_CONTEXT_CACHE_ENABLED")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
