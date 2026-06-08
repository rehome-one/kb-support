"""Integration-тесты агрегатов отчётов (E8-3, #167) — требуют Postgres.

Новые методы репозитория: `operator_stats` (resolved-anchor), `rating_distribution`,
`reopen_stats`. Изоляция — историческое окно 2001-01 + откатываемая транзакция (как #165).
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
from api.tickets.enums import TicketStatus
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Агрегаты отчётов требуют живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")
_WINDOW = StatsPeriod(from_date=datetime.date(2001, 1, 1), to_date=datetime.date(2001, 1, 31))
_OP1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_OP2 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")


def _dt(month: int, day: int) -> datetime.datetime:
    return datetime.datetime(2001, month, day, tzinfo=datetime.UTC)


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
        number=f"RH-2001R-{idx:05d}",
        subject="seed",
        description="seed",
        type=kw.pop("type", "OTHER"),
        channel=kw.pop("channel", "EMAIL"),
        status=status.value,
        requester_id=uuid.uuid4(),
        created_at=created,
        **kw,
    )


def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            # op1: 2 решены в окне (1440 + 2880 → avg 2160); rating 5/5.
            _ticket(
                1,
                created=_dt(1, 4),
                status=TicketStatus.RESOLVED,
                assignee_id=_OP1,
                resolved_at=_dt(1, 5),
                rating=5,
            ),
            _ticket(
                2,
                created=_dt(1, 8),
                status=TicketStatus.RESOLVED,
                assignee_id=_OP1,
                resolved_at=_dt(1, 10),
                rating=5,
                reopened_count=0,
            ),
            # op2: 1 решена в окне (1440); rating 3.
            _ticket(
                3,
                created=_dt(1, 14),
                status=TicketStatus.RESOLVED,
                assignee_id=_OP2,
                resolved_at=_dt(1, 15),
                rating=3,
            ),
            # без assignee, решена в окне → НЕ в operators; reopened; создана в окне.
            _ticket(
                5,
                created=_dt(1, 19),
                status=TicketStatus.OPEN,
                reopened_count=2,
            ),
            # op1, решена ВНЕ окна (март) → НЕ в operators; создана вне окна → не в volume/rating.
            _ticket(
                4,
                created=_dt(2, 28),
                status=TicketStatus.RESOLVED,
                assignee_id=_OP1,
                resolved_at=_dt(3, 1),
                rating=5,
            ),
        ]
    )


def test_operator_stats_resolved_anchor() -> None:
    async def body(session: AsyncSession) -> None:
        _seed(session)
        await session.flush()
        stats = await AnalyticsRepository(session).operator_stats(_WINDOW)
        # Порядок: по убыванию resolved_count → op1(2) раньше op2(1).
        assert [(s.operator_id, s.resolved_count) for s in stats] == [(_OP1, 2), (_OP2, 1)]
        by_op = {s.operator_id: s for s in stats}
        assert by_op[_OP1].avg_resolution_minutes == pytest.approx(2160.0)  # (1440+2880)/2
        assert by_op[_OP2].avg_resolution_minutes == pytest.approx(1440.0)

    _in_rolled_back_session(body)


def test_rating_distribution() -> None:
    async def body(session: AsyncSession) -> None:
        _seed(session)
        await session.flush()
        dist = await AnalyticsRepository(session).rating_distribution(_WINDOW)
        # created∈окно с rating: t1(5),t2(5),t3(3); t5 без rating; t4 вне окна.
        assert dist == {5: 2, 3: 1}

    _in_rolled_back_session(body)


def test_reopen_stats() -> None:
    async def body(session: AsyncSession) -> None:
        _seed(session)
        await session.flush()
        total, reopened = await AnalyticsRepository(session).reopen_stats(_WINDOW)
        # created∈окно: t1,t2,t3,t5 = 4; reopened_count>0: только t5 → 1.
        assert (total, reopened) == (4, 1)

    _in_rolled_back_session(body)
