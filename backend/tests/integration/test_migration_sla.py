"""Integration-тест миграции SLA (E4-1 #85): upgrade/downgrade + ON DELETE SET NULL.

Требует живой Postgres — CI (service container) или локально `POSTGRES_AVAILABLE=1`.
Синхронный (как test_migration_tickets): `alembic.command.*` сам поднимает async-engine
через env.py, поэтому не внутри активного event loop.

Проверяет (условия ревью плана #85):
- upgrade head создаёт `business_hours` + `sla_policies` и FK `fk_tickets_sla_policy_id`;
- серверные дефолты (is_active=true, priority=0, schedule/applies_to '{}');
- ON DELETE SET NULL на ОБОИХ FK (business_hours→sla_policies, sla_policies→tickets);
- downgrade -1 снимает FK с tickets и удаляет обе таблицы.
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

PREV_REVISION = "20260601_120000_chat_uniq"


def _tables() -> set[str]:
    async def _inner() -> set[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _tickets_fk_names() -> set[str]:
    async def _inner() -> set[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                fks = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("tickets"))
                return {name for fk in fks if (name := fk.get("name")) is not None}
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _run_dml_checks() -> None:
    """Серверные дефолты + ON DELETE SET NULL на обоих FK (через сырой SQL)."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        bh_id, p1_id, p2_id, t_id = (uuid.uuid4() for _ in range(4))
        try:
            async with engine.begin() as conn:
                # business_hours: только обязательные поля → проверяем server_default.
                await conn.execute(
                    text(
                        "INSERT INTO business_hours (id, name, timezone)" " VALUES (:id, :n, :tz)"
                    ),
                    {"id": bh_id, "n": "bh", "tz": "Europe/Moscow"},
                )
                row = (
                    await conn.execute(
                        text("SELECT is_active, schedule FROM business_hours WHERE id = :id"),
                        {"id": bh_id},
                    )
                ).one()
                assert row.is_active is True
                assert row.schedule == {}

                # sla_policy, ссылающаяся на business_hours → проверяем server_default.
                await conn.execute(
                    text(
                        "INSERT INTO sla_policies"
                        " (id, name, first_response_minutes, resolution_minutes, business_hours_id)"
                        " VALUES (:id, :n, 15, 120, :bh)"
                    ),
                    {"id": p1_id, "n": "p1", "bh": bh_id},
                )
                row = (
                    await conn.execute(
                        text(
                            "SELECT priority, is_active, applies_to FROM sla_policies"
                            " WHERE id = :id"
                        ),
                        {"id": p1_id},
                    )
                ).one()
                assert row.priority == 0
                assert row.is_active is True
                assert row.applies_to == {}

                # FK1: ON DELETE SET NULL business_hours → sla_policies.business_hours_id.
                await conn.execute(text("DELETE FROM business_hours WHERE id = :id"), {"id": bh_id})
                bh_ref = (
                    await conn.execute(
                        text("SELECT business_hours_id FROM sla_policies WHERE id = :id"),
                        {"id": p1_id},
                    )
                ).scalar_one()
                assert bh_ref is None

                # FK2: ON DELETE SET NULL sla_policies → tickets.sla_policy_id.
                await conn.execute(
                    text(
                        "INSERT INTO sla_policies"
                        " (id, name, first_response_minutes, resolution_minutes)"
                        " VALUES (:id, :n, 30, 240)"
                    ),
                    {"id": p2_id, "n": "p2"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO tickets"
                        " (id, number, subject, description, status, priority, type, channel,"
                        "  access_level, requester_id, sla_policy_id)"
                        " VALUES (:id, :num, 's', 'd', 'NEW', 'normal', 'PAYMENT', 'EMAIL',"
                        "  'logged', :req, :pol)"
                    ),
                    {
                        "id": t_id,
                        "num": f"RH-TEST-{t_id.hex[:8]}",
                        "req": uuid.uuid4(),
                        "pol": p2_id,
                    },
                )
                await conn.execute(text("DELETE FROM sla_policies WHERE id = :id"), {"id": p2_id})
                pol_ref = (
                    await conn.execute(
                        text("SELECT sla_policy_id FROM tickets WHERE id = :id"),
                        {"id": t_id},
                    )
                ).scalar_one()
                assert pol_ref is None

                # Чистка тестовой заявки (таблица tickets переживает downgrade).
                await conn.execute(text("DELETE FROM tickets WHERE id = :id"), {"id": t_id})
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def test_sla_migration_upgrade_downgrade() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    try:
        tables = _tables()
        assert "business_hours" in tables
        assert "sla_policies" in tables
        assert "fk_tickets_sla_policy_id" in _tickets_fk_names()

        _run_dml_checks()

        command.downgrade(cfg, PREV_REVISION)
        tables_after = _tables()
        assert "sla_policies" not in tables_after
        assert "business_hours" not in tables_after
        assert "fk_tickets_sla_policy_id" not in _tickets_fk_names()
    finally:
        # Восстановить head независимо от исхода (для последующих тестов CI).
        command.upgrade(cfg, "head")
