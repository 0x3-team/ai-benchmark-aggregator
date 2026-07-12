from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="sqlite:///./data/benchmark_ledger.db",
        alias="DATABASE_URL",
    )
    snapshot_storage_backend: str = Field(default="local", alias="SNAPSHOT_STORAGE_BACKEND")
    snapshot_local_root: Path = Field(default=Path("./data/snapshots"), alias="SNAPSHOT_LOCAL_ROOT")
    http_timeout_seconds: float = Field(default=30.0, alias="HTTP_TIMEOUT_SECONDS")
    http_user_agent: str = Field(default="benchmark-ledger/0.1", alias="HTTP_USER_AGENT")
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")
    ingestion_fail_fast: bool = Field(default=False, alias="INGESTION_FAIL_FAST")


@lru_cache
def get_settings() -> Settings:
    return Settings()
