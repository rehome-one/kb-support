"""Integration-тесты порядка/конфликтов правил автоматизации (E5 #111) — требуют Postgres.

§3.9 ТЗ: правила применяются в порядке `order` (apply_order asc, тай-брейк id); конфликт
действий над одним полем = last-write-wins по порядку (ADR-0008 Реш.7). Здесь проверяется
СУЩЕСТВУЮЩЕЕ поведение #105/#106/#107 (прод-код не меняется) на продакшен-пути врезки
(`TicketRepository.create`/`apply_update`).

Паттерн `_autobegin` (как `test_automation_engine`): продакшен-autobegin сессия с откатом
в конце → общая тест-БД не загрязняется.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import AUTOMATION_ACTOR_ID
from api.automation.models import AutomationRule
from api.automation.repository import AutomationRuleRepository
from api.config import get_settings
from api.tickets.enums import TicketPriority, TicketStatus, TicketTeam, TicketType
from api.tickets.history import TicketHistoryRepository
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketCreate, TicketUpdate

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Порядок правил автоматизации требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
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


async def _isolate_rules(session: AsyncSession) -> None:
    """Удалить все правила В ТРАНЗАКЦИИ (откат `_autobegin` восстановит накопленные).

    Тест-БД общая: contract/admin-тесты КОММИТЯТ on_create-правила (напр. FRAUD→critical),
    которые иначе фаерились бы на нашу заявку и ломали детерминизм порядка. Удаление видно
    только внутри нашей транзакции и откатывается в конце — чужие данные целы."""
    await session.execute(delete(AutomationRule))
    await session.flush()


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


def test_rules_apply_in_order_last_write_wins() -> None:
    """Два on_create-правила на одно поле (priority): итог — последнего по `order`."""

    async def body(session: AsyncSession) -> None:
        await _isolate_rules(session)
        await _add_rule(
            session,
            name="first",
            conditions={"types": ["FRAUD"]},
            actions=[{"action": "set_priority", "params": {"priority": "high"}}],
            apply_order=0,
        )
        await _add_rule(
            session,
            name="second",
            conditions={"types": ["FRAUD"]},
            actions=[{"action": "set_priority", "params": {"priority": "low"}}],
            apply_order=1,
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="s", type=TicketType.FRAUD), _PRINCIPAL
        )
        # LWW по порядку: итог = apply_order=1 (low). Будь порядок обратным — было бы high,
        # поэтому само значение доказывает применение в порядке `order`.
        assert ticket.priority == TicketPriority.LOW.value
        # Оба правила реально применились (две automation-записи priority_changed). Порядок
        # СТРОК истории не ассертим: в одной транзакции `created_at`=func.now() одинаков для
        # всех → тай-брейк по id недетерминирован; истинный порядок виден в итоговом значении.
        prio = [
            r
            for r in await _history(session, ticket.id)
            if r.action == "priority_changed" and r.actor_id == AUTOMATION_ACTOR_ID
        ]
        assert len(prio) == 2
        assert {r.to_value["priority"] for r in prio} == {"high", "low"}

    _autobegin(body)


def test_conflicting_set_status_last_by_order_wins() -> None:
    """Буквальный пример ТЗ: два set_status → итог последнего по `order` (NEW→OPEN→PENDING)."""

    async def body(session: AsyncSession) -> None:
        await _isolate_rules(session)
        await _add_rule(
            session,
            name="to-open",
            conditions={},
            actions=[{"action": "set_status", "params": {"status": "OPEN"}}],
            apply_order=0,
        )
        await _add_rule(
            session,
            name="to-pending",
            conditions={},
            actions=[{"action": "set_status", "params": {"status": "PENDING"}}],
            apply_order=1,
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="s", type=TicketType.OTHER), _PRINCIPAL
        )
        assert ticket.status == TicketStatus.PENDING.value  # последнее по порядку

    _autobegin(body)


def test_fraud_scenario_end_to_end() -> None:
    """Сквозной сценарий ТЗ: type=FRAUD → priority=critical + маршрутизация в legal + notify.

    team=legal реализуется `assign` (ставит team без перехода state-machine; escalate из NEW
    запрещён ALLOWED_TRANSITIONS). notify — seam (ADR-0008 Реш.3), best-effort, не падает."""

    async def body(session: AsyncSession) -> None:
        await _isolate_rules(session)
        operator_id = uuid.uuid4()
        await _add_rule(
            session,
            name="fraud-route",
            conditions={"types": ["FRAUD"]},
            actions=[
                {"action": "set_priority", "params": {"priority": "critical"}},
                {
                    "action": "assign",
                    "params": {
                        "strategy": "direct",
                        "operator_id": str(operator_id),
                        "team": "legal",
                    },
                },
                {"action": "notify", "params": {"recipient": "supervisor"}},
            ],
            apply_order=0,
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="мошенничество с оплатой", type=TicketType.FRAUD), _PRINCIPAL
        )
        assert ticket.priority == TicketPriority.CRITICAL.value
        assert ticket.team == TicketTeam.LEGAL.value
        assert ticket.assignee_id == operator_id
        # Цепочка применилась через системного актора (трассируемость).
        actions = {
            r.action
            for r in await _history(session, ticket.id)
            if r.actor_id == AUTOMATION_ACTOR_ID
        }
        assert {"priority_changed", "reassigned"} <= actions

    _autobegin(body)


def test_on_update_rules_apply_in_order() -> None:
    """Порядок/LWW работает и на on_update: два правила set_priority по order."""

    async def body(session: AsyncSession) -> None:
        await _isolate_rules(session)
        await _add_rule(
            session,
            name="upd-first",
            trigger="on_update",
            conditions={},
            actions=[{"action": "set_priority", "params": {"priority": "high"}}],
            apply_order=0,
        )
        await _add_rule(
            session,
            name="upd-second",
            trigger="on_update",
            conditions={},
            actions=[{"action": "set_priority", "params": {"priority": "low"}}],
            apply_order=1,
        )
        await session.flush()
        repo = TicketRepository(session)
        ticket = await repo.create(TicketCreate(subject="s", type=TicketType.PAYMENT), _PRINCIPAL)
        await repo.apply_update(ticket, TicketUpdate(subject="updated"), _PRINCIPAL)
        assert ticket.priority == TicketPriority.LOW.value  # последнее по порядку

    _autobegin(body)
