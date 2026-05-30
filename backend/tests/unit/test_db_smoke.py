"""Smoke tests на DB foundation: Settings + engine pool + SELECT 1."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings, get_settings
from api.db import engine


def test_settings_loads_database_url() -> None:
    """Settings корректно подтягивает database_url из env / default."""
    s = get_settings()
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_settings_pool_size_in_valid_range() -> None:
    s = get_settings()
    assert 1 <= s.database_pool_size <= 100
    assert 0 <= s.database_pool_max_overflow <= 200


@pytest.fixture
def env_kbs_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Подмена env переменной KBS_DATABASE_URL."""
    override = "postgresql+asyncpg://test:test@localhost:5432/testdb"
    monkeypatch.setenv("KBS_DATABASE_URL", override)
    # Сбросить lru_cache, чтобы Settings парсил env заново.
    get_settings.cache_clear()
    yield override
    get_settings.cache_clear()


def test_settings_loads_from_env_var(env_kbs_database_url: str) -> None:
    """KBS_DATABASE_URL env переменная подменяет default."""
    s = Settings()
    assert s.database_url == env_kbs_database_url


def test_engine_pool_config_applied() -> None:
    """Engine pool сконфигурирован из Settings."""
    s = get_settings()
    # pool.size() возвращает текущий target размер pool'а.
    assert engine.pool.size() == s.database_pool_size


@pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason=(
        "SELECT 1 требует живой Postgres. Запускается в CI (service container)"
        " и локально при выставленном POSTGRES_AVAILABLE=1."
    ),
)
@pytest.mark.asyncio
async def test_select_1(db_session: AsyncSession) -> None:
    """Smoke `SELECT 1` через session factory + rollback фикстуру."""
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
