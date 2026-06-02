"""Integration-тесты репозиториев SLA (E4-1 #85): чтение + порядок матчинга.

Требует живой Postgres. Проверяет контракт, на который опирается матчинг #87:
`list_active` отдаёт только активные политики по убыванию `priority`.

Синхронный (как test_migration_*): свой NullPool-engine внутри `asyncio.run` +
rollback транзакции — изоляция и один event loop (избегаем cross-loop teardown
session-scoped движка с asyncpg).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.config import get_settings
from api.sla.models import BusinessHours, SLAPolicy
from api.sla.repository import BusinessHoursRepository, SLAPolicyRepository

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Требует живой Postgres (CI service container или POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")


def _in_rolled_back_session(body: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Выполнить `body(session)` в транзакции, которая откатывается (изоляция)."""

    async def _inner() -> T:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                trans = await conn.begin()
                factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
                async with factory() as session:
                    result = await body(session)
                await trans.rollback()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_list_active_orders_by_priority_desc_and_excludes_inactive() -> None:
    async def body(session: AsyncSession) -> list[str]:
        session.add_all(
            [
                SLAPolicy(
                    name="low",
                    applies_to={},
                    first_response_minutes=60,
                    resolution_minutes=480,
                    priority=1,
                ),
                SLAPolicy(
                    name="high",
                    applies_to={},
                    first_response_minutes=15,
                    resolution_minutes=120,
                    priority=10,
                ),
                SLAPolicy(
                    name="inactive",
                    applies_to={},
                    first_response_minutes=30,
                    resolution_minutes=240,
                    priority=99,
                    is_active=False,
                ),
            ]
        )
        await session.flush()
        return [p.name for p in await SLAPolicyRepository(session).list_active()]

    names = _in_rolled_back_session(body)
    assert "inactive" not in names  # неактивные исключены
    # high (priority=10) раньше low (priority=1) — порядок матчинга #87.
    assert names.index("high") < names.index("low")


def test_get_returns_policy_and_business_hours() -> None:
    async def body(session: AsyncSession) -> tuple[uuid.UUID | None, str | None]:
        bh = BusinessHours(name="bh", timezone="Europe/Moscow", schedule={})
        session.add(bh)
        await session.flush()
        policy = SLAPolicy(
            name="p",
            applies_to={},
            first_response_minutes=15,
            resolution_minutes=120,
            business_hours_id=bh.id,
        )
        session.add(policy)
        await session.flush()

        got_policy = await SLAPolicyRepository(session).get(policy.id)
        got_bh = await BusinessHoursRepository(session).get(bh.id)
        assert got_policy is not None and got_bh is not None
        return got_policy.business_hours_id, got_bh.timezone

    bh_ref, tz = _in_rolled_back_session(body)
    assert bh_ref is not None
    assert tz == "Europe/Moscow"
