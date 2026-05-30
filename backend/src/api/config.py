"""Application settings via pydantic-settings.

Все настройки загружаются из env (или `.env` файла для local dev).
Префикс env-переменных: `KBS_*` (`KBS_DATABASE_URL`, `KBS_DATABASE_POOL_SIZE`, ...).

На bootstrap'е (#2) — только DB-related поля. Расширится по мере появления
Redis (E4), external API клиентов (E3), Keycloak (E3) и т.д.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Глобальные настройки сервиса."""

    model_config = SettingsConfigDict(
        env_prefix="KBS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://kbsupport:devpass@localhost:5432/kbsupport",
        description=(
            "PostgreSQL async DSN (asyncpg driver). "
            "TLS на этом этапе не enforce'ится; для prod добавить sslmode=require "
            "+ sslrootcert через параметры query string."
        ),
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_max_overflow: int = Field(default=20, ge=0, le=200)
    database_echo: bool = Field(
        default=False,
        description="SQLAlchemy echo для debug. В production — всегда False.",
    )
    history_retention_days: int = Field(
        default=1825,
        ge=1,
        description=(
            "Срок хранения TicketHistory (NFR-1.4 — 5 лет = 1825 дней). "
            "Фактический cleanup-воркер — отдельный Issue в E8; здесь только "
            "конфигурируемая политика."
        ),
    )
    log_level: str = Field(
        default="INFO",
        description="Уровень JSON-логирования (DEBUG/INFO/WARNING/ERROR).",
    )
    # --- Keycloak Bearer JWT (#29). Пустой auth_jwks_url → auth не сконфигурирован
    # (fail-closed 401). Реалм/issuer/audience задаются в окружении деплоя. ---
    auth_jwks_url: str = Field(
        default="",
        description="URL JWKS Keycloak (.../protocol/openid-connect/certs).",
    )
    auth_issuer: str = Field(default="", description="Ожидаемый iss токена (пусто → не проверять).")
    auth_audience: str = Field(
        default="", description="Ожидаемый aud токена (пусто → не проверять)."
    )
    auth_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    auth_leeway: int = Field(default=0, ge=0, description="Допуск по времени (сек) для exp/nbf.")
    auth_jwks_cache_ttl: int = Field(
        default=300, ge=1, description="TTL кеша JWKS (сек) до принудительного рефреша."
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached Settings instance.

    `lru_cache` гарантирует один Settings объект на процесс, чтобы
    pydantic-settings не парсил env при каждом вызове.
    """
    return Settings()
