"""Integration-тест миграции automation_rules (E5-1 #103): upgrade/downgrade.

Требует живой Postgres — CI (service container) или локально `POSTGRES_AVAILABLE=1`.
Синхронный (как test_migration_sla): `alembic.command.*` сам поднимает async-engine
через env.py, поэтому не внутри активного event loop.

Проверяет (условия ревью плана #103):
- upgrade head создаёт таблицу `automation_rules` И индекс
  `ix_automation_rules_trigger_active_apply_order`;
- серверные дефолты (is_active=true, apply_order=0, conditions '{}', actions '[]');
- downgrade -1 удаляет таблицу и индекс; идемпотентность (повторный upgrade).
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

PREV_REVISION = "20260603_120000_sla_pauses"
_INDEX = "ix_automation_rules_trigger_active_apply_order"


def _tables() -> set[str]:
    async def _inner() -> set[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _automation_indexes() -> set[str]:
    async def _inner() -> set[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                idx = await conn.run_sync(lambda c: inspect(c).get_indexes("automation_rules"))
                return {name for i in idx if (name := i.get("name")) is not None}
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _run_default_checks() -> None:
    """Серверные дефолты: вставляем только обязательные поля, читаем остальное."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        rule_id = uuid.uuid4()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO automation_rules (id, name, trigger)" " VALUES (:id, :n, :t)"
                    ),
                    {"id": rule_id, "n": "r", "t": "on_create"},
                )
                row = (
                    await conn.execute(
                        text(
                            "SELECT is_active, apply_order, conditions, actions"
                            " FROM automation_rules WHERE id = :id"
                        ),
                        {"id": rule_id},
                    )
                ).one()
                assert row.is_active is True
                assert row.apply_order == 0
                assert row.conditions == {}
                assert row.actions == []
                await conn.execute(
                    text("DELETE FROM automation_rules WHERE id = :id"), {"id": rule_id}
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def test_automation_migration_upgrade_downgrade() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    try:
        assert "automation_rules" in _tables()
        assert _INDEX in _automation_indexes()

        _run_default_checks()

        command.downgrade(cfg, PREV_REVISION)
        assert "automation_rules" not in _tables()
    finally:
        # Восстановить head независимо от исхода (для последующих тестов CI).
        command.upgrade(cfg, "head")
