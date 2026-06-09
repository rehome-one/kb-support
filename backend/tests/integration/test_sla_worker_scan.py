"""Integration-тест скана SLA-воркера (E4-6, #90) — требует Postgres.

Проверяет РЕАЛЬНЫЙ SQL-предикат выборки (COALESCE-семантика breach, исключение
терминальных статусов) против живой БД — то, что unit-тесты на компиляции не ловят.

Тест-БД общая: заявки накапливаются. Чтобы выборка была детерминированной
независимо от накопленных данных, активной просроченной заявке выставляется
дедлайн в ДАЛЁКОМ прошлом (сортируется первой при ORDER BY due_at ASC → в пределах
batch_limit). Resolved-заявка должна быть исключена.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.sla.worker.hooks import SlaBreachEvent
from api.sla.worker.scan import scan_and_escalate
from api.tickets.enums import TicketCaseState, TicketStatus, TicketTeam
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Скан SLA требует живой Postgres (CI service container / POSTGRES_AVAILABLE=1).",
)

UTC = datetime.UTC
_NOW = datetime.datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_FAR_PAST = datetime.datetime(2000, 1, 1, tzinfo=UTC)

_OPERATOR = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)


@pytest.fixture
def factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)

    async def _get_test_session() -> AsyncIterator[AsyncSession]:
        async with async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _get_test_session
    app.dependency_overrides[get_current_principal] = lambda: _OPERATOR
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_principal, None)
    asyncio.run(engine.dispose())


def _create_ticket(client: TestClient) -> uuid.UUID:
    resp = client.post("/api/v1/support/tickets", json={"subject": "s", "type": "OTHER"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["data"]["id"])


def test_scan_returns_active_breached_excludes_resolved(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    with TestClient(app) as client:
        active_id = _create_ticket(client)
        resolved_id = _create_ticket(client)

    async def _run() -> list[SlaBreachEvent]:
        # Просрочить активную заявку (дедлайн в далёком прошлом) и закрыть вторую.
        async with factory() as session:
            active = await session.get(Ticket, active_id)
            assert active is not None
            active.resolution_due_at = _FAR_PAST
            active.status = TicketStatus.OPEN.value

            resolved = await session.get(Ticket, resolved_id)
            assert resolved is not None
            resolved.resolution_due_at = _FAR_PAST
            resolved.resolved_at = _FAR_PAST
            resolved.status = TicketStatus.RESOLVED.value
            await session.commit()

        events: list[SlaBreachEvent] = []

        async def hook(event: SlaBreachEvent) -> None:
            events.append(event)

        async with factory() as session:
            return await scan_and_escalate(session, now=_NOW, hook=hook, batch_limit=500)

    events = asyncio.run(_run())
    ids = {e.ticket_id for e in events}
    assert active_id in ids  # активная просроченная — эскалирована
    assert resolved_id not in ids  # resolved — исключена


def test_scan_excludes_paused_within_deadline(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    with TestClient(app) as client:
        paused_id = _create_ticket(client)

    async def _run() -> set[uuid.UUID]:
        async with factory() as session:
            paused = await session.get(Ticket, paused_id)
            assert paused is not None
            # Нога первого ответа закрыта (ответили) → breach только по решению.
            paused.first_responded_at = _NOW - datetime.timedelta(hours=3)
            # Решение на паузе ДО наступления дедлайна: as_of заморожено → не breach.
            paused.resolution_due_at = _NOW + datetime.timedelta(hours=1)
            paused.sla_paused_at = _NOW - datetime.timedelta(hours=2)
            paused.status = TicketStatus.PENDING.value
            await session.commit()

        events: list[SlaBreachEvent] = []

        async def hook(event: SlaBreachEvent) -> None:
            events.append(event)

        async with factory() as session:
            await scan_and_escalate(session, now=_NOW, hook=hook, batch_limit=500)
        return {e.ticket_id for e in events}

    assert paused_id not in asyncio.run(_run())


def test_scan_returns_overdue_payout_claim(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    # Просроченная выплата претензии (PAYOUT_PENDING + payout_due_at в прошлом) — эскалируется
    # тем же воркером (E10-6 #196), нога breach = payout.
    with TestClient(app) as client:
        payout_id = _create_ticket(client)

    async def _run() -> list[SlaBreachEvent]:
        async with factory() as session:
            t = await session.get(Ticket, payout_id)
            assert t is not None
            t.case_state = TicketCaseState.PAYOUT_PENDING.value
            t.payout_due_at = _FAR_PAST
            t.resolution_due_at = None  # без resolution-breach: ловим именно payout
            t.first_response_due_at = None
            t.status = TicketStatus.OPEN.value
            await session.commit()

        events: list[SlaBreachEvent] = []

        async def hook(event: SlaBreachEvent) -> None:
            events.append(event)

        async with factory() as session:
            return await scan_and_escalate(session, now=_NOW, hook=hook, batch_limit=500)

    events = asyncio.run(_run())
    by_id = {e.ticket_id: e for e in events}
    assert payout_id in by_id
    assert by_id[payout_id].payout_breached is True
