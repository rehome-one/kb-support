"""Integration-тесты эскалации по SLA-breach через движок (#108) — требуют Postgres.

Продакшен-autobegin сессия (factory(), урок #107). Покрывают:
- просроченная заявка + on_sla_breach-правило escalate → ESCALATED + history (боевой путь);
- ТРИГГЕР-ИЗОЛЯЦИЯ: on_create-правило НЕ срабатывает на breach-проходе (условие 5);
- actor КОММИТИТ: эскалация видна в НОВОЙ сессии — пережила commit (условие 6);
- BEST-EFFORT: действие с DB-ошибкой изолировано SAVEPOINT'ом, скан не падает,
  заявка цела, сессия пригодна к commit (условие 7).
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.system_actors import AUTOMATION_ACTOR_ID
from api.automation import actions
from api.automation.enums import AutomationActionType
from api.automation.models import AutomationRule
from api.automation.repository import AutomationRuleRepository
from api.automation.sla_breach import make_sla_breach_hook
from api.config import get_settings
from api.sla.worker.scan import scan_and_escalate
from api.tickets.enums import (
    TicketChannel,
    TicketPriority,
    TicketStatus,
    TicketTeam,
    TicketType,
)
from api.tickets.history import TicketHistory, TicketHistoryRepository
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Эскалация по SLA-breach требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _autobegin(body: Callable[[AsyncSession], Awaitable[T]]) -> T:
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


async def _seed_breached(
    session: AsyncSession, *, status: TicketStatus = TicketStatus.OPEN
) -> Ticket:
    """Просроченная по решению заявка (resolution_due_at в прошлом, не resolved)."""
    ticket = Ticket(
        number=f"T-{uuid.uuid4().hex[:10]}",
        subject="s",
        description="d",
        type=TicketType.OTHER.value,
        channel=TicketChannel.WEB_FORM.value,
        requester_id=uuid.uuid4(),
        team=TicketTeam.SUPPORT.value,
        status=status.value,
        resolution_due_at=_now() - datetime.timedelta(hours=2),
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def _add_rule(session: AsyncSession, **values: Any) -> uuid.UUID:
    base: dict[str, Any] = {
        "name": "rule",
        "trigger": "on_sla_breach",
        "conditions": {},
        "actions": [],
        "is_active": True,
    }
    base.update(values)
    rule = await AutomationRuleRepository(session).create(base)
    return rule.id


def test_breach_escalates_via_on_sla_breach_rule() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _seed_breached(session)
        await _add_rule(session, actions=[{"action": "escalate", "params": {}}])
        events = await scan_and_escalate(
            session, now=_now(), hook=make_sla_breach_hook(session), batch_limit=100
        )
        assert any(e.ticket_id == ticket.id for e in events)
        assert ticket.status == TicketStatus.ESCALATED.value
        rows = list(await TicketHistoryRepository(session).list_for_ticket(ticket.id))
        assert any(r.actor_id == AUTOMATION_ACTOR_ID for r in rows)

    _autobegin(body)


def test_on_create_rule_not_fired_on_breach_pass() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _seed_breached(session)
        # on_create-правило (set_priority) НЕ должно сработать на breach-проходе.
        await _add_rule(
            session,
            trigger="on_create",
            actions=[{"action": "set_priority", "params": {"priority": "critical"}}],
        )
        # on_sla_breach-правило (escalate) ДОЛЖНО сработать.
        await _add_rule(session, actions=[{"action": "escalate", "params": {}}])
        await scan_and_escalate(
            session, now=_now(), hook=make_sla_breach_hook(session), batch_limit=100
        )
        assert ticket.status == TicketStatus.ESCALATED.value  # on_sla_breach сработал
        assert ticket.priority != TicketPriority.CRITICAL.value  # on_create НЕ сработал

    _autobegin(body)


def test_scan_commits_escalation_visible_in_new_session() -> None:
    """Actor коммитит: эскалация переживает commit и видна в НОВОЙ сессии (условие 6)."""

    async def _inner() -> None:
        eng = create_async_engine(get_settings().database_url, poolclass=NullPool)
        factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        ticket_id: uuid.UUID | None = None
        rule_id: uuid.UUID | None = None
        try:
            async with factory() as s1:
                ticket = await _seed_breached(s1)
                ticket_id = ticket.id
                rule_id = await _add_rule(s1, actions=[{"action": "escalate", "params": {}}])
                await scan_and_escalate(
                    s1, now=_now(), hook=make_sla_breach_hook(s1), batch_limit=100
                )
                await s1.commit()  # как делает actor с #108
            async with factory() as s2:
                fresh = await s2.get(Ticket, ticket_id)
                assert fresh is not None
                assert fresh.status == TicketStatus.ESCALATED.value  # пережило commit
        finally:
            # Уборка закоммиченных строк, чтобы не загрязнять общую тест-БД.
            async with factory() as sc:
                if ticket_id is not None:
                    await sc.execute(
                        delete(TicketHistory).where(TicketHistory.ticket_id == ticket_id)
                    )
                    await sc.execute(delete(Ticket).where(Ticket.id == ticket_id))
                if rule_id is not None:
                    await sc.execute(delete(AutomationRule).where(AutomationRule.id == rule_id))
                await sc.commit()
            await eng.dispose()

    asyncio.run(_inner())


def test_failing_action_isolated_scan_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB-ошибка действия изолирована SAVEPOINT'ом: скан не падает, escalate цел,
    poison откатан, сессия пригодна к commit (условие 7, best-effort на breach-пути)."""

    async def _poison(
        session: AsyncSession, ticket: Ticket, _params: Any, _rule_id: uuid.UUID
    ) -> None:
        # Намеренный poison: NOT NULL колонка → реальный DB-abort на flush (тест
        # SAVEPOINT-изоляции). type: ignore — присваивание None в non-nullable поле осознанно.
        ticket.requester_id = None  # type: ignore[assignment]
        await session.flush()

    monkeypatch.setitem(actions._DISPATCH, AutomationActionType.ADD_TAG.value, _poison)

    async def body(session: AsyncSession) -> None:
        ticket = await _seed_breached(session)
        original_requester = ticket.requester_id
        await _add_rule(
            session,
            actions=[
                {"action": "escalate", "params": {}},
                {"action": "add_tag", "params": {"tags": ["x"]}},  # → poison
            ],
        )
        # Скан НЕ должен бросить, несмотря на DB-ошибку действия.
        await scan_and_escalate(
            session, now=_now(), hook=make_sla_breach_hook(session), batch_limit=100
        )
        assert ticket.status == TicketStatus.ESCALATED.value  # escalate пережил
        assert ticket.requester_id == original_requester  # poison откатан (refresh)
        # Сессия не отравлена → пригодна к работе (как commit у actor'а).
        count = (await session.execute(select(Ticket.id).limit(1))).first()
        assert count is not None

    _autobegin(body)
