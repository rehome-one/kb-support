"""Integration-тесты репозитория AutomationRule (E5-1 #103): чтение + порядок.

Требует живой Postgres. Проверяет контракт, на который опирается матчинг #105:
`list_active` отдаёт только активные правила в порядке `apply_order` asc (тай-брейк
по `id`), с опциональным фильтром по `trigger` (None = все активные).

Синхронный (как test_migration_*): свой NullPool-engine внутри `asyncio.run` +
rollback транзакции — изоляция и один event loop (избегаем cross-loop teardown
session-scoped движка с asyncpg, урок #85).
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

from api.automation.models import AutomationRule
from api.automation.repository import AutomationRuleRepository
from api.config import get_settings

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


def _rule(
    name: str, trigger: str, order: int, *, active: bool = True, **kw: object
) -> AutomationRule:
    return AutomationRule(
        name=name,
        trigger=trigger,
        conditions={},
        actions=[],
        apply_order=order,
        is_active=active,
        **kw,
    )


def test_list_active_orders_by_apply_order_filters_trigger_and_excludes_inactive() -> None:
    async def body(session: AsyncSession) -> None:
        repo = AutomationRuleRepository(session)
        session.add_all(
            [
                _rule("a-late", "on_create", 10),
                _rule("b-early", "on_create", 1),
                _rule("c-update", "on_update", 5),
                _rule("d-inactive", "on_create", 1, active=False),
            ]
        )
        await session.flush()

        # Тест-БД общая (admin/contract-тесты коммитят правила) → относительные
        # проверки по СВОИМ правилам, не точное равенство (как test_sla_repository).
        mine = {"a-late", "b-early", "c-update", "d-inactive"}

        # Все активные: inactive исключён; порядок apply_order asc (1<5<10).
        active = [r.name for r in await repo.list_active() if r.name in mine]
        assert "d-inactive" not in active
        assert active.index("b-early") < active.index("c-update") < active.index("a-late")

        # Фильтр по триггеру: только on_create активные (c-update — on_update — исключён).
        on_create = [r.name for r in await repo.list_active(trigger="on_create") if r.name in mine]
        assert "c-update" not in on_create
        assert on_create.index("b-early") < on_create.index("a-late")

        # time_based: ни одного из моих правил.
        tb = {r.name for r in await repo.list_active(trigger="time_based")}
        assert not (mine & tb)

        # list_all включает неактивные (мои 4 ⊆ результат).
        assert mine <= {r.name for r in await repo.list_all()}

    _in_rolled_back_session(body)


def test_list_active_tiebreak_by_id() -> None:
    async def body(session: AsyncSession) -> None:
        repo = AutomationRuleRepository(session)
        id_low = uuid.UUID(int=1)
        id_high = uuid.UUID(int=2)
        # Одинаковый apply_order → тай-брейк по id (детерминизм для #105).
        session.add_all(
            [
                _rule("high-id", "on_create", 3, id=id_high),
                _rule("low-id", "on_create", 3, id=id_low),
            ]
        )
        await session.flush()

        # Среди моих двух (равный apply_order) — тай-брейк по id: low-id раньше high-id.
        mine = [r.name for r in await repo.list_active() if r.name in {"low-id", "high-id"}]
        assert mine == ["low-id", "high-id"]

    _in_rolled_back_session(body)


def test_create_get_update_round_trip() -> None:
    async def body(session: AsyncSession) -> None:
        repo = AutomationRuleRepository(session)
        created = await repo.create(
            {"name": "fraud", "trigger": "on_create", "conditions": {}, "actions": []}
        )
        fetched = await repo.get(created.id)
        assert fetched is not None and fetched.name == "fraud"
        assert fetched.is_active is True  # ORM-default отражает server_default намерение

        await repo.update(fetched, {"name": "fraud-2", "apply_order": 7})
        again = await repo.get(created.id)
        assert again is not None and again.name == "fraud-2" and again.apply_order == 7

    _in_rolled_back_session(body)
