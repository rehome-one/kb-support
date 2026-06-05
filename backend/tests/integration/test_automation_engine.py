"""Integration-тесты оркестрации автоматизации (E5-5 #107) — требуют Postgres.

Продакшен-путь: сессия из `async_sessionmaker` с AUTOBEGIN (НЕ внешний `conn.begin()`-
биндинг — иначе savepoint ведёт себя нерепрезентативно, см. ревью плана #107). Откат в
конце — без загрязнения общей тест-БД.

Покрывают: on_create/on_update срабатывают end-to-end через `TicketRepository`; non-
matching правило пропускается; цепочка действий применяется целиком; **DB-poisoning
действие изолировано SAVEPOINT'ом — транзакция заявки не отравлена** (условие 4).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import AUTOMATION_ACTOR_ID
from api.automation import engine
from api.automation.repository import AutomationRuleRepository
from api.config import get_settings
from api.tickets.enums import TicketTeam, TicketType
from api.tickets.history import TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketCreate, TicketUpdate

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Оркестрация автоматизации требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")
_PRINCIPAL = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)


def _autobegin(body: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Продакшен-autobegin сессия (factory()); откат в конце — без загрязнения БД."""

    async def _inner() -> T:
        eng = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                try:
                    return await body(session)
                finally:
                    await session.rollback()
        finally:
            await eng.dispose()

    return asyncio.run(_inner())


async def _add_rule(session: AsyncSession, **values: Any) -> uuid.UUID:
    base: dict[str, Any] = {
        "name": "rule",
        "trigger": "on_create",
        "conditions": {},
        "actions": [],
        "is_active": True,
    }
    base.update(values)
    rule = await AutomationRuleRepository(session).create(base)
    return rule.id


async def _history(session: AsyncSession, ticket_id: uuid.UUID) -> list[Any]:
    return list(await TicketHistoryRepository(session).list_for_ticket(ticket_id))


def test_on_create_rule_fires_end_to_end() -> None:
    async def body(session: AsyncSession) -> None:
        await _add_rule(
            session,
            trigger="on_create",
            conditions={"types": ["FRAUD"]},
            actions=[{"action": "set_priority", "params": {"priority": "critical"}}],
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="мошенничество", type=TicketType.FRAUD), _PRINCIPAL
        )
        assert ticket.priority == "critical"  # правило применилось при создании
        rows = await _history(session, ticket.id)
        assert any(
            r.action == "priority_changed" and r.actor_id == AUTOMATION_ACTOR_ID for r in rows
        )

    _autobegin(body)


def test_non_matching_rule_skipped() -> None:
    async def body(session: AsyncSession) -> None:
        await _add_rule(
            session,
            trigger="on_create",
            conditions={"types": ["PAYMENT"]},  # не FRAUD
            actions=[{"action": "set_priority", "params": {"priority": "critical"}}],
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="s", type=TicketType.FRAUD), _PRINCIPAL
        )
        assert ticket.priority == "normal"  # правило не подошло → дефолт

    _autobegin(body)


def test_on_update_rule_fires_and_no_recursion() -> None:
    async def body(session: AsyncSession) -> None:
        await _add_rule(
            session,
            trigger="on_update",
            conditions={},
            actions=[
                {"action": "set_priority", "params": {"priority": "high"}},
                {"action": "add_tag", "params": {"tags": ["chain"]}},
            ],
        )
        await session.flush()
        repo = TicketRepository(session)
        ticket = await repo.create(TicketCreate(subject="s", type=TicketType.PAYMENT), _PRINCIPAL)
        await repo.apply_update(ticket, TicketUpdate(subject="updated"), _PRINCIPAL)
        # Цепочка применилась целиком:
        assert ticket.priority == "high"
        assert "chain" in ticket.tags
        # Ре-триггера нет: ровно одна automation-строка priority_changed (не задвоено).
        auto_prio = [
            r
            for r in await _history(session, ticket.id)
            if r.action == "priority_changed" and r.actor_id == AUTOMATION_ACTOR_ID
        ]
        assert len(auto_prio) == 1

    _autobegin(body)


def test_db_poisoning_action_isolated_by_savepoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Действие с РЕАЛЬНОЙ DB-ошибкой (NOT NULL violation на flush) изолировано
    SAVEPOINT'ом: транзакция заявки не отравлена, заявка цела и согласована."""

    async def _poison(
        session: AsyncSession, ticket: Ticket, action: Any, *, rule_id: uuid.UUID, trigger: str
    ) -> bool:
        ticket.requester_id = None  # type: ignore[assignment]
        await session.flush()  # NOT NULL → asyncpg error, отравил бы tx без savepoint
        return True

    monkeypatch.setattr(engine, "apply_action", _poison)

    async def body(session: AsyncSession) -> None:
        await _add_rule(
            session,
            trigger="on_create",
            conditions={},  # catch-all
            actions=[{"action": "set_priority", "params": {"priority": "high"}}],
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="s", type=TicketType.FRAUD), _PRINCIPAL
        )
        # Сессия НЕ отравлена: запрос после savepoint-восстановления выполняется.
        count = (await session.execute(select(func.count()).select_from(Ticket))).scalar()
        assert count is not None and count >= 1
        # Заявка создана и согласована: requester_id восстановлен (refresh после rollback).
        assert ticket.requester_id is not None

    _autobegin(body)
