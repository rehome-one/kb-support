"""Integration-тесты агрегации аналитики (E8-1, #165) — требуют Postgres.

Изоляция от накопленных данных общей тест-БД (:5433): сид в **историческом окне**
(2001-01, вне реальных дат) + запрос ровно за это окно → когортные метрики точны
(урок #111). `now` для breach-предиката инжектируется фиксированным (детерминизм —
условие 5 ревью #165). Сессия — откатываемая транзакция (паттерн #85/test_sla_repository).

`tickets.open` — снапшот (без фильтра периода), поэтому видит и внешние строки;
проверяем его **дельтой** (добавление open-заявки ВНЕ периода меняет open на +1),
а не абсолютным значением.
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
from api.analytics.service import AnalyticsService
from api.clients.cache import InMemoryCache
from api.config import get_settings
from api.tickets.enums import TicketChannel, TicketStatus, TicketType
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Агрегация аналитики требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")

_WINDOW = StatsPeriod(from_date=datetime.date(2001, 1, 1), to_date=datetime.date(2001, 1, 31))
_NOW = datetime.datetime(2001, 2, 15, tzinfo=datetime.UTC)


def _dt(month: int, day: int, hour: int = 0, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2001, month, day, hour, minute, tzinfo=datetime.UTC)


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
    """Минимальный Ticket с историческим created_at. Прочие поля — через kw."""
    return Ticket(
        number=f"RH-2001-{idx:05d}",
        subject="seed",
        description="seed",
        type=kw.pop("type", TicketType.OTHER.value),
        channel=kw.pop("channel", TicketChannel.EMAIL.value),
        status=status.value,
        requester_id=uuid.uuid4(),
        created_at=created,
        **kw,
    )


def _seed_window(session: AsyncSession) -> None:
    session.add_all(
        [
            # t1: ответ и решение В СРОК; CLOSED; AI_CHAT/PAYMENT; rating=5.
            _ticket(
                1,
                created=_dt(1, 5),
                status=TicketStatus.CLOSED,
                type=TicketType.PAYMENT.value,
                channel=TicketChannel.AI_CHAT.value,
                first_responded_at=_dt(1, 5, 0, 10),
                first_response_due_at=_dt(1, 5, 0, 15),
                resolved_at=_dt(1, 6),
                resolution_due_at=_dt(1, 7),
                rating=5,
            ),
            # t2: ОБЕ ноги нарушены; RESOLVED; EMAIL/OTHER; rating=2; reopened.
            _ticket(
                2,
                created=_dt(1, 10),
                status=TicketStatus.RESOLVED,
                type=TicketType.OTHER.value,
                channel=TicketChannel.EMAIL.value,
                first_responded_at=_dt(1, 10, 0, 30),
                first_response_due_at=_dt(1, 10, 0, 15),
                resolved_at=_dt(1, 12),
                resolution_due_at=_dt(1, 11),
                rating=2,
                reopened_count=1,
            ),
            # t3: открыта и просрочена на момент now; AI_CHAT/PAYMENT; без ответа/оценки.
            _ticket(
                3,
                created=_dt(1, 15),
                status=TicketStatus.OPEN,
                type=TicketType.PAYMENT.value,
                channel=TicketChannel.AI_CHAT.value,
                first_response_due_at=_dt(1, 15, 0, 15),
                resolution_due_at=_dt(1, 20),
            ),
        ]
    )


def test_aggregates_exact_on_isolated_window() -> None:
    async def body(session: AsyncSession) -> None:
        _seed_window(session)
        await session.flush()
        service = AnalyticsService(
            AnalyticsRepository(session),
            InMemoryCache(now=lambda: 0.0),
            now=lambda: _NOW,
            ttl_seconds=60,
        )
        stats = await service.get_stats(_WINDOW)

        # Когортные объёмы (created ∈ окно).
        assert stats.tickets.total == 3
        assert stats.tickets.resolved == 1
        assert stats.tickets.closed == 1
        assert stats.tickets.by_type == {"PAYMENT": 2, "OTHER": 1}
        assert stats.tickets.by_channel == {"AI_CHAT": 2, "EMAIL": 1}

        # SLA: compliance по завершившим ногу в окне (t1,t2); breaches по now (t2,t3).
        assert stats.sla.first_response_compliance_pct == pytest.approx(50.0)
        assert stats.sla.resolution_compliance_pct == pytest.approx(50.0)
        assert stats.sla.breaches == 2

        # Производительность (wall-clock минуты).
        assert stats.performance.avg_first_response_minutes == pytest.approx(20.0)
        assert stats.performance.avg_resolution_minutes == pytest.approx(2160.0)
        assert stats.performance.reopened_rate_pct == pytest.approx(100.0 / 3)

        # Качество и AI-чат.
        assert stats.quality.avg_rating == pytest.approx(3.5)
        assert stats.quality.ratings_count == 2
        assert stats.ai_chat.escalated_count == 2
        assert stats.ai_chat.containment_rate_pct is None  # seam #166

    _in_rolled_back_session(body)


def test_empty_period_yields_zero_denominator_nulls() -> None:
    async def body(session: AsyncSession) -> None:
        repo = AnalyticsRepository(session)
        empty = StatsPeriod(from_date=datetime.date(1999, 1, 1), to_date=datetime.date(1999, 1, 31))

        counts = await repo.ticket_counts(empty)
        sla = await repo.sla_stats(empty, _NOW)
        perf = await repo.performance_stats(empty)
        quality = await repo.quality_stats(empty)

        assert counts.total == 0
        assert counts.by_type == {}
        assert counts.by_channel == {}
        # Нулевой знаменатель → None (не 0, не NaN, не исключение).
        assert sla.first_response_compliance_pct is None
        assert sla.resolution_compliance_pct is None
        assert sla.breaches == 0
        assert perf.avg_first_response_minutes is None
        assert perf.avg_resolution_minutes is None
        assert perf.reopened_rate_pct is None
        assert quality.avg_rating is None
        assert quality.ratings_count == 0
        assert await repo.ai_chat_escalated(empty) == 0

    _in_rolled_back_session(body)


def test_open_is_snapshot_not_cohort() -> None:
    """Заявка, открытая ВНЕ периода запроса, всё равно увеличивает `open` (снапшот)."""

    async def body(session: AsyncSession) -> None:
        repo = AnalyticsRepository(session)
        before = (await repo.ticket_counts(_WINDOW)).open

        # OPEN-заявка, СОЗДАННАЯ вне окна запроса (1998-06): когорта её бы НЕ учла.
        session.add(_ticket(99, created=_dt(6, 1).replace(year=1998), status=TicketStatus.OPEN))
        await session.flush()

        after = await repo.ticket_counts(_WINDOW)
        assert after.open == before + 1  # снапшот учёл внеоконную заявку
        assert after.total == 0  # ...но когортный total (created ∈ 2001-01) её не считает

    _in_rolled_back_session(body)
