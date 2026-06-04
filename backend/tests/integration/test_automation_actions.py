"""Integration-тесты исполнителей действий автоматизации (E5-4 #106) — требуют Postgres.

Проверяют реальные мутации заявки + запись в неизменяемый журнал §3.7: actor =
`AUTOMATION_ACTOR_ID`, `automation_rule_id` в `to_value`; дедуп тегов; изоляция
запрещённого перехода (best-effort: False, заявка цела). Rolled-back сессия (#85).
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

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import AUTOMATION_ACTOR_ID
from api.automation.actions import apply_action
from api.config import get_settings
from api.tickets.enums import TicketStatus, TicketTeam
from api.tickets.history import TicketHistory, TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketCreate

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Исполнители автоматизации требуют живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")
_RULE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_PRINCIPAL = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)


def _in_rolled_back_session(body: Callable[[AsyncSession], Awaitable[T]]) -> T:
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


async def _new_ticket(session: AsyncSession, **over: object) -> Ticket:
    ticket = await TicketRepository(session).create(
        TicketCreate(subject="s", type="PAYMENT", **over),  # type: ignore[arg-type]
        _PRINCIPAL,
    )
    return ticket


async def _history(session: AsyncSession, ticket_id: uuid.UUID) -> list[TicketHistory]:
    return list(await TicketHistoryRepository(session).list_for_ticket(ticket_id))


def test_set_priority_mutates_and_audits() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _new_ticket(session, priority="normal")
        ok = await apply_action(
            session,
            ticket,
            {"action": "set_priority", "params": {"priority": "high"}},
            rule_id=_RULE_ID,
            trigger="on_create",
        )
        assert ok is True
        assert ticket.priority == "high"
        rows = await _history(session, ticket.id)
        prio = [r for r in rows if r.action == "priority_changed"]
        assert prio, "ожидалась строка PRIORITY_CHANGED"
        assert prio[0].actor_id == AUTOMATION_ACTOR_ID
        assert prio[0].to_value is not None
        assert prio[0].to_value["automation_rule_id"] == str(_RULE_ID)

    _in_rolled_back_session(body)


def test_add_tag_dedup() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _new_ticket(session)
        action = {"action": "add_tag", "params": {"tags": ["urgent"]}}
        assert await apply_action(session, ticket, action, rule_id=_RULE_ID, trigger="on_create")
        assert "urgent" in ticket.tags
        first = len([r for r in await _history(session, ticket.id) if r.action == "tags_updated"])
        # Повтор того же тега → дедуп: тег не задваивается, новой строки журнала нет.
        assert await apply_action(session, ticket, action, rule_id=_RULE_ID, trigger="on_create")
        assert ticket.tags.count("urgent") == 1
        second = len([r for r in await _history(session, ticket.id) if r.action == "tags_updated"])
        assert second == first

    _in_rolled_back_session(body)


def test_set_status_valid_transition() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _new_ticket(session)  # NEW
        ok = await apply_action(
            session,
            ticket,
            {"action": "set_status", "params": {"status": "OPEN"}},
            rule_id=_RULE_ID,
            trigger="on_create",
        )
        assert ok is True
        assert ticket.status == TicketStatus.OPEN.value
        rows = await _history(session, ticket.id)
        assert any(r.action == "status_changed" and r.actor_id == AUTOMATION_ACTOR_ID for r in rows)

    _in_rolled_back_session(body)


def test_invalid_transition_isolated() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _new_ticket(session)  # NEW → RESOLVED запрещён
        ok = await apply_action(
            session,
            ticket,
            {"action": "set_status", "params": {"status": "RESOLVED"}},
            rule_id=_RULE_ID,
            trigger="on_create",
        )
        assert ok is False  # best-effort: сбой изолирован
        assert ticket.status == TicketStatus.NEW.value  # заявка не сломана

    _in_rolled_back_session(body)


def test_assign_direct_audits_actor_and_rule() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _new_ticket(session)
        operator = uuid.uuid4()
        ok = await apply_action(
            session,
            ticket,
            {
                "action": "assign",
                "params": {"strategy": "direct", "operator_id": str(operator), "team": "support"},
            },
            rule_id=_RULE_ID,
            trigger="on_update",
        )
        assert ok is True
        assert ticket.assignee_id == operator
        rows = await _history(session, ticket.id)
        reassigned = [r for r in rows if r.action == "reassigned"]
        assert reassigned and reassigned[0].actor_id == AUTOMATION_ACTOR_ID
        assert reassigned[0].to_value is not None
        assert reassigned[0].to_value["automation_rule_id"] == str(_RULE_ID)

    _in_rolled_back_session(body)


def test_escalate_sets_status() -> None:
    async def body(session: AsyncSession) -> None:
        ticket = await _new_ticket(session)
        await apply_action(
            session,
            ticket,
            {"action": "set_status", "params": {"status": "OPEN"}},
            rule_id=_RULE_ID,
            trigger="on_create",
        )
        ok = await apply_action(
            session,
            ticket,
            {"action": "escalate", "params": {"team": "legal"}},
            rule_id=_RULE_ID,
            trigger="on_sla_breach",
        )
        assert ok is True
        assert ticket.status == TicketStatus.ESCALATED.value
        assert ticket.team == TicketTeam.LEGAL.value

    _in_rolled_back_session(body)
