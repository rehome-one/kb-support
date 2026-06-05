"""Integration-тесты стратегий автоназначения (#109) — требуют Postgres.

Продакшен-autobegin сессия (factory(), НЕ внешний conn.begin()-биндинг — урок #107).
Откат в конце — без загрязнения общей тест-БД.

Покрывают live-query часть (чистые селекторы — в unit):
- least_load выбирает наименее загруженного в ЦЕЛЕВОЙ команде;
- терминальные (RESOLVED/CLOSED) НЕ считаются загрузкой;
- team-scope: чужая команда и team=NULL не влияют;
- round_robin детерминированно чередует по кумулятивному счётчику (Вариант A);
- текущая заявка исключена из счётчика;
- переназначение уже назначенной заявки → REASSIGNED с непустым from_value;
- e2e через run_rules: on_create-правило assign/least_load реально проставляет assignee;
- пустой пул → наблюдаемый недо-резолв (метрика deferred), assignee не ставится.
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
from api.automation import engine
from api.automation.assignment import resolve_assignee
from api.automation.enums import AssignStrategy
from api.automation.metrics import AUTOMATION_ACTION_DEFERRED
from api.automation.repository import AutomationRuleRepository
from api.config import get_settings
from api.tickets.enums import TicketChannel, TicketStatus, TicketTeam, TicketType
from api.tickets.history import TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketCreate

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Стратегии назначения требуют живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")

OP1 = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
OP2 = uuid.UUID("00000000-0000-4000-8000-0000000000a2")
OP3 = uuid.UUID("00000000-0000-4000-8000-0000000000a3")
POOL = [OP1, OP2, OP3]

_PRINCIPAL = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)


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


async def _seed(
    session: AsyncSession,
    *,
    assignee_id: uuid.UUID | None,
    team: TicketTeam | None,
    status: TicketStatus = TicketStatus.OPEN,
) -> Ticket:
    ticket = Ticket(
        number=f"T-{uuid.uuid4().hex[:10]}",
        subject="s",
        description="d",
        type=TicketType.OTHER.value,
        channel=TicketChannel.WEB_FORM.value,
        requester_id=uuid.uuid4(),
        team=team.value if team is not None else None,
        assignee_id=assignee_id,
        status=status.value,
    )
    session.add(ticket)
    await session.flush()
    return ticket


def test_least_load_picks_minimum_in_target_team() -> None:
    async def body(session: AsyncSession) -> None:
        cur = await _seed(session, assignee_id=None, team=TicketTeam.SUPPORT)
        # OP1: 2 активных, OP2: 1, OP3: 0 (в SUPPORT).
        await _seed(session, assignee_id=OP1, team=TicketTeam.SUPPORT)
        await _seed(session, assignee_id=OP1, team=TicketTeam.SUPPORT)
        await _seed(session, assignee_id=OP2, team=TicketTeam.SUPPORT)
        chosen = await resolve_assignee(
            session,
            strategy=AssignStrategy.LEAST_LOAD,
            team=TicketTeam.SUPPORT,
            pool=POOL,
            current_ticket_id=cur.id,
        )
        assert chosen == OP3  # наименее загружен

    _autobegin(body)


def test_least_load_excludes_terminal_and_other_team() -> None:
    async def body(session: AsyncSession) -> None:
        cur = await _seed(session, assignee_id=None, team=TicketTeam.SUPPORT)
        # OP1: 1 активная в SUPPORT.
        await _seed(session, assignee_id=OP1, team=TicketTeam.SUPPORT)
        # OP2: терминальные (не считаются) + активная в ЧУЖОЙ команде (не считается).
        await _seed(session, assignee_id=OP2, team=TicketTeam.SUPPORT, status=TicketStatus.RESOLVED)
        await _seed(session, assignee_id=OP2, team=TicketTeam.SUPPORT, status=TicketStatus.CLOSED)
        await _seed(session, assignee_id=OP2, team=TicketTeam.LEGAL)
        # OP3: активная с team=NULL (не считается — `=` к NULL = false).
        await _seed(session, assignee_id=OP3, team=None)
        chosen = await resolve_assignee(
            session,
            strategy=AssignStrategy.LEAST_LOAD,
            team=TicketTeam.SUPPORT,
            pool=POOL,
            current_ticket_id=cur.id,
        )
        # У OP2 и OP3 активная загрузка в SUPPORT = 0 → тай-брейк по operator_id → OP2.
        assert chosen == OP2

    _autobegin(body)


def test_least_load_excludes_current_ticket() -> None:
    async def body(session: AsyncSession) -> None:
        # Текущая заявка уже назначена OP1 и в SUPPORT — НЕ должна считаться себе в счёт.
        cur = await _seed(session, assignee_id=OP1, team=TicketTeam.SUPPORT)
        # Реальная загрузка: OP2 — 1, OP1/OP3 — 0 (текущая исключена).
        await _seed(session, assignee_id=OP2, team=TicketTeam.SUPPORT)
        chosen = await resolve_assignee(
            session,
            strategy=AssignStrategy.LEAST_LOAD,
            team=TicketTeam.SUPPORT,
            pool=POOL,
            current_ticket_id=cur.id,
        )
        assert chosen == OP1  # тай-брейк OP1<OP3 при равном нуле; текущая не учтена

    _autobegin(body)


def test_round_robin_deterministic_by_cumulative_count() -> None:
    async def body(session: AsyncSession) -> None:
        cur = await _seed(session, assignee_id=None, team=TicketTeam.SUPPORT)
        # Кумулятивно (все статусы) на пул в SUPPORT = 2 → индекс 2 → OP3.
        await _seed(session, assignee_id=OP1, team=TicketTeam.SUPPORT, status=TicketStatus.CLOSED)
        await _seed(session, assignee_id=OP2, team=TicketTeam.SUPPORT)
        chosen = await resolve_assignee(
            session,
            strategy=AssignStrategy.ROUND_ROBIN,
            team=TicketTeam.SUPPORT,
            pool=POOL,
            current_ticket_id=cur.id,
        )
        assert chosen == OP3  # POOL[2 % 3]

    _autobegin(body)


def test_empty_pool_returns_none() -> None:
    async def body(session: AsyncSession) -> None:
        cur = await _seed(session, assignee_id=None, team=TicketTeam.SUPPORT)
        chosen = await resolve_assignee(
            session,
            strategy=AssignStrategy.LEAST_LOAD,
            team=TicketTeam.SUPPORT,
            pool=None,
            current_ticket_id=cur.id,
        )
        assert chosen is None

    _autobegin(body)


async def _add_rule(session: AsyncSession, **values: object) -> uuid.UUID:
    base: dict[str, object] = {
        "name": "assign-rule",
        "trigger": "on_create",
        "conditions": {},
        "actions": [],
        "is_active": True,
    }
    base.update(values)
    rule = await AutomationRuleRepository(session).create(base)
    return rule.id


def test_e2e_on_create_least_load_assigns_and_audits() -> None:
    async def body(session: AsyncSession) -> None:
        # Засев загрузки: OP1 занят (1), OP2/OP3 — 0 → least_load выберет OP2 (тай-брейк).
        await _seed(session, assignee_id=OP1, team=TicketTeam.SUPPORT)
        await _add_rule(
            session,
            actions=[
                {
                    "action": "assign",
                    "params": {
                        "strategy": "least_load",
                        "team": "support",
                        "pool": [str(OP1), str(OP2), str(OP3)],
                    },
                }
            ],
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="s", type=TicketType.OTHER), _PRINCIPAL
        )
        assert ticket.assignee_id == OP2
        rows = list(await TicketHistoryRepository(session).list_for_ticket(ticket.id))
        assert any(r.action == "reassigned" and r.actor_id == AUTOMATION_ACTOR_ID for r in rows)

    _autobegin(body)


def test_e2e_reassignment_records_previous_assignee() -> None:
    async def body(session: AsyncSession) -> None:
        await _add_rule(
            session,
            trigger="on_update",
            actions=[
                {
                    "action": "assign",
                    "params": {
                        "strategy": "least_load",
                        "team": "support",
                        "pool": [str(OP1)],
                    },
                }
            ],
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="s", type=TicketType.OTHER), _PRINCIPAL
        )
        ticket.assignee_id = OP2  # предварительно назначена OP2
        await session.flush()
        await engine.run_rules(session, ticket, "on_update")
        assert ticket.assignee_id == OP1  # переназначена пулом
        rows = list(await TicketHistoryRepository(session).list_for_ticket(ticket.id))
        reassign = [
            r for r in rows if r.action == "reassigned" and r.actor_id == AUTOMATION_ACTOR_ID
        ]
        assert reassign and reassign[-1].from_value == {"assignee_id": str(OP2)}

    _autobegin(body)


def test_e2e_empty_pool_defers_observably() -> None:
    async def body(session: AsyncSession) -> None:
        before = AUTOMATION_ACTION_DEFERRED.labels(
            action="assign", reason="strategy_least_load_no_pool"
        )._value.get()
        await _add_rule(
            session,
            actions=[{"action": "assign", "params": {"strategy": "least_load", "team": "support"}}],
        )
        await session.flush()
        ticket = await TicketRepository(session).create(
            TicketCreate(subject="s", type=TicketType.OTHER), _PRINCIPAL
        )
        assert ticket.assignee_id is None  # недо-резолв: не назначено
        after = AUTOMATION_ACTION_DEFERRED.labels(
            action="assign", reason="strategy_least_load_no_pool"
        )._value.get()
        assert after == before + 1  # наблюдаемо (метрика), не тихо

    _autobegin(body)
