"""Конфигурация приложения: окружение читается из ai-harness/.env."""

from __future__ import annotations

import base64
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://harness:harness@localhost:5433/ai_harness"
    test_database_url: str = "postgresql+asyncpg://harness:harness@localhost:5433/ai_harness_test"
    # AES-256-GCM ключ (base64 от 32 байт); пустое значение допустимо, пока контур
    # провайдеров не используется (этап 4)
    ai_harness_token_key: str = ""
    session_ttl_hours: int = 12
    daemon_tick_seconds: int = 30

    @property
    def token_key_bytes(self) -> bytes:
        if not self.ai_harness_token_key:
            raise RuntimeError("AI_HARNESS_TOKEN_KEY не задан: заполните ai-harness/.env")
        raw = base64.b64decode(self.ai_harness_token_key)
        if len(raw) != 32:
            raise RuntimeError("AI_HARNESS_TOKEN_KEY должен быть base64 от 32 байт")
        return raw


@lru_cache
def get_settings() -> Settings:
    return Settings()
