"""Integration-тест миграции canned_responses (E6-1 #125): upgrade/downgrade.

Требует живой Postgres — CI (service container) или локально `POSTGRES_AVAILABLE=1`.
Синхронный (как test_migration_automation): `alembic.command.*` сам поднимает
async-engine через env.py, поэтому не внутри активного event loop.

Проверяет: upgrade head создаёт таблицу `canned_responses`; серверный дефолт
usage_count=0; downgrade -1 удаляет таблицу; восстановление head.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from api.config import get_settings

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason=(
        "Миграции требуют живой Postgres. Запускается в CI (service container)"
        " и локально при POSTGRES_AVAILABLE=1."
    ),
)

PREV_REVISION = "20260604_120000_automation"


def _tables() -> set[str]:
    async def _inner() -> set[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _run_default_checks() -> None:
    """Серверный дефолт usage_count=0: вставляем только обязательные поля, читаем остальное."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        canned_id = uuid.uuid4()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO canned_responses (id, title, body) VALUES (:id, :t, :b)"),
                    {"id": canned_id, "t": "t", "b": "b"},
                )
                row = (
                    await conn.execute(
                        text("SELECT usage_count FROM canned_responses WHERE id = :id"),
                        {"id": canned_id},
                    )
                ).one()
                assert row.usage_count == 0
                await conn.execute(
                    text("DELETE FROM canned_responses WHERE id = :id"), {"id": canned_id}
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def test_canned_migration_upgrade_downgrade() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    try:
        assert "canned_responses" in _tables()
        _run_default_checks()

        command.downgrade(cfg, PREV_REVISION)
        assert "canned_responses" not in _tables()
    finally:
        # Восстановить head независимо от исхода (для последующих тестов CI).
        command.upgrade(cfg, "head")
