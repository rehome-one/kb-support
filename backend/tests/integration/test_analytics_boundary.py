"""Граница периода UTC на уровне SQL-запроса (E8-8, #172) — требует Postgres.

`test_period` пиннит только арифметику `StatsPeriod.start/end_exclusive`. Здесь —
что РЕАЛЬНЫЙ SQL-фильтр `[start, end_exclusive)` (`repository.py`) включает весь
`to_date` против живых строк: заявка на `to 23:59:59 UTC` входит, на `to+1 00:00:00
UTC` (== end_exclusive) — нет, на `from 00:00:00 UTC` — входит.

Покрыты обе анкер-клаузы: `created_at` (когортные объёмы) и `resolved_at`
(resolved-anchor отчёта operators) — это разные SQL-предикаты.

Изоляция — историческое окно 2001-01 + откатываемая транзакция (как #165/#111).
Load-bearing: замена `end_exclusive` на начало `to`-дня или `<` на потерю
последней секунды уронит ассерт.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.analytics.period import StatsPeriod
from api.analytics.repository import AnalyticsRepository
from api.config import get_settings
from api.tickets.enums import TicketChannel, TicketStatus, TicketType
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Boundary-тест аналитики требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")

_WINDOW = StatsPeriod(from_date=datetime.date(2001, 1, 1), to_date=datetime.date(2001, 1, 31))
# Три граничные метки UTC относительно окна 2001-01.
_FROM_START = datetime.datetime(2001, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)  # входит
_TO_LAST_SECOND = datetime.datetime(2001, 1, 31, 23, 59, 59, tzinfo=datetime.UTC)  # входит
_AFTER_END = datetime.datetime(
    2001, 2, 1, 0, 0, 0, tzinfo=datetime.UTC
)  # == end_exclusive → НЕ входит


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


def _ticket(idx: int, *, created: datetime.datetime, status: TicketStatus, **kw: object) -> Ticket:
    return Ticket(
        number=f"RH-2001-{idx:05d}",
        subject="seed",
        description="seed",
        type=TicketType.OTHER.value,
        channel=TicketChannel.EMAIL.value,
        status=status.value,
        requester_id=uuid.uuid4(),
        created_at=created,
        **kw,
    )


def test_created_at_boundary_to_date_inclusive() -> None:
    """created_at: from 00:00:00 и to 23:59:59 входят, to+1 00:00:00 — нет → total == 2."""

    async def body(session: AsyncSession) -> None:
        session.add_all(
            [
                _ticket(1, created=_FROM_START, status=TicketStatus.OPEN),
                _ticket(2, created=_TO_LAST_SECOND, status=TicketStatus.OPEN),
                _ticket(3, created=_AFTER_END, status=TicketStatus.OPEN),
            ]
        )
        await session.flush()
        counts = await AnalyticsRepository(session).ticket_counts(_WINDOW)
        assert counts.total == 2  # t3 (to+1 00:00:00 == end_exclusive) исключена

    _in_rolled_back_session(body)


def test_resolved_at_boundary_operators_to_date_inclusive() -> None:
    """resolved_at (operators resolved-anchor): to 23:59:59 входит, to+1 00:00:00 — нет."""

    async def body(session: AsyncSession) -> None:
        operator = uuid.uuid4()
        created = datetime.datetime(2001, 1, 10, tzinfo=datetime.UTC)
        session.add_all(
            [
                _ticket(
                    10,
                    created=created,
                    status=TicketStatus.RESOLVED,
                    assignee_id=operator,
                    resolved_at=_TO_LAST_SECOND,  # входит
                ),
                _ticket(
                    11,
                    created=created,
                    status=TicketStatus.RESOLVED,
                    assignee_id=operator,
                    resolved_at=_AFTER_END,  # == end_exclusive → НЕ входит
                ),
            ]
        )
        await session.flush()
        stats = await AnalyticsRepository(session).operator_stats(_WINDOW)
        by_op = {s.operator_id: s for s in stats}
        assert by_op[operator].resolved_count == 1  # только заявка, решённая в окне

    _in_rolled_back_session(body)
