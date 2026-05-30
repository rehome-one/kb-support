"""Integration-тест миграции tickets (DoD #5): upgrade head / downgrade -1.

Требует живой Postgres — запускается в CI (service container) и локально при
`POSTGRES_AVAILABLE=1`. Иначе пропускается (паттерн `test_db_smoke.test_select_1`).

Тест синхронный: `alembic.command.*` сам поднимает async-engine через
`env.py` (`asyncio.run`), поэтому не должен исполняться внутри активного event
loop — отсюда отказ от `async def`.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
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

INIT_REVISION = "20260530_120000_init"


def _inspect_tables() -> set[str]:
    """Список таблиц через одноразовый async-engine (sync-обёртка)."""

    async def _inner() -> set[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                names = await conn.run_sync(lambda c: inspect(c).get_table_names())
                return set(names)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _index_names() -> set[str]:
    async def _inner() -> set[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                idx = await conn.run_sync(lambda c: inspect(c).get_indexes("tickets"))
                return {name for i in idx if (name := i.get("name")) is not None}
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_tickets_migration_upgrade_downgrade() -> None:
    """`upgrade head` создаёт `tickets` + индексы; `downgrade -1` удаляет."""
    cfg = Config("alembic.ini")

    command.upgrade(cfg, "head")
    try:
        assert "tickets" in _inspect_tables()
        indexes = _index_names()
        assert {
            "ix_tickets_requester_id",
            "ix_tickets_assignee_id",
            "ix_tickets_status_created_at",
        } <= indexes

        command.downgrade(cfg, INIT_REVISION)
        assert "tickets" not in _inspect_tables()
    finally:
        # Восстановить head для последующих шагов/тестов CI независимо от исхода.
        command.upgrade(cfg, "head")
