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
    """6 заявок в окне 2001-01 — мутационно-стойкий сид (условия MINOR-1/2 ревью PR #174).

    Включает граничные кейсы `completed_at == due_at` (t4 — нарушение по строгому `<`,
    пиннит границу) и заявку, нарушенную ТОЛЬКО по resolution-ноге (t5 — fr в срок, решение
    просрочено), чтобы инверсия оператора/строгости в compliance/breach роняла ассерт.
    Асимметрия met≠missed (3/5 fr, 2/5 res) ловит полную инверсию.
    """
    session.add_all(
        [
            # t1: обе ноги В СРОК (строго <); CLOSED; AI_CHAT/PAYMENT; rating=5. Не breach.
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
            # t2: обе ноги нарушены; RESOLVED; EMAIL/OTHER; rating=2; reopened. breach(res).
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
            # t3: открыта и просрочена на момент now; AI_CHAT/PAYMENT; без ответа. breach(fr+res).
            _ticket(
                3,
                created=_dt(1, 15),
                status=TicketStatus.OPEN,
                type=TicketType.PAYMENT.value,
                channel=TicketChannel.AI_CHAT.value,
                first_response_due_at=_dt(1, 15, 0, 15),
                resolution_due_at=_dt(1, 20),
            ),
            # t4: ГРАНИЦА — обе метки РОВНО на дедлайне (== due ⇒ нарушение по строгому <);
            # CLOSED; PHONE/ACCOUNT; rating=4. breach(res, as_of==due≥due).
            _ticket(
                4,
                created=_dt(1, 18),
                status=TicketStatus.CLOSED,
                type=TicketType.ACCOUNT.value,
                channel=TicketChannel.PHONE.value,
                first_responded_at=_dt(1, 18, 0, 15),
                first_response_due_at=_dt(1, 18, 0, 15),
                resolved_at=_dt(1, 19),
                resolution_due_at=_dt(1, 19),
                rating=4,
            ),
            # t5: ТОЛЬКО resolution нарушена (fr в срок, решение просрочено); RESOLVED;
            # EMAIL/CONTRACT; без оценки. breach(res only) — изолирует resolution-клаузу.
            _ticket(
                5,
                created=_dt(1, 20),
                status=TicketStatus.RESOLVED,
                type=TicketType.CONTRACT.value,
                channel=TicketChannel.EMAIL.value,
                first_responded_at=_dt(1, 20, 0, 5),
                first_response_due_at=_dt(1, 20, 0, 15),
                resolved_at=_dt(1, 25),
                resolution_due_at=_dt(1, 22),
            ),
            # t6: обе ноги в срок; CLOSED; AI_CHAT/MAINTENANCE; rating=3. Не breach.
            _ticket(
                6,
                created=_dt(1, 8),
                status=TicketStatus.CLOSED,
                type=TicketType.MAINTENANCE.value,
                channel=TicketChannel.AI_CHAT.value,
                first_responded_at=_dt(1, 8, 0, 8),
                first_response_due_at=_dt(1, 8, 0, 15),
                resolved_at=_dt(1, 9),
                resolution_due_at=_dt(1, 10),
                rating=3,
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
        assert stats.tickets.total == 6
        assert stats.tickets.resolved == 2  # t2, t5
        assert stats.tickets.closed == 3  # t1, t4, t6
        assert stats.tickets.by_type == {
            "PAYMENT": 2,
            "OTHER": 1,
            "ACCOUNT": 1,
            "CONTRACT": 1,
            "MAINTENANCE": 1,
        }
        assert stats.tickets.by_channel == {"AI_CHAT": 3, "EMAIL": 2, "PHONE": 1}

        # SLA: compliance СТРОГО до дедлайна (t4 на границе == due ⇒ НЕ met). breaches по now.
        # fr-знам=5 (t1,t2,t4,t5,t6), met=3 (t1,t5,t6) → 60%.
        assert stats.sla.first_response_compliance_pct == pytest.approx(60.0)
        # res-знам=5 (t1,t2,t4,t5,t6), met=2 (t1,t6) → 40%.
        assert stats.sla.resolution_compliance_pct == pytest.approx(40.0)
        # breaches: t2(res), t3(fr+res), t4(res-граница), t5(res-only) = 4.
        assert stats.sla.breaches == 4

        # Производительность (wall-clock минуты).
        # fr: (10+30+15+5+8)/5 = 13.6.
        assert stats.performance.avg_first_response_minutes == pytest.approx(13.6)
        # res: (1440+2880+1440+7200+1440)/5 = 2880.
        assert stats.performance.avg_resolution_minutes == pytest.approx(2880.0)
        assert stats.performance.reopened_rate_pct == pytest.approx(100.0 / 6)  # t2 из 6

        # Качество и AI-чат.
        assert stats.quality.avg_rating == pytest.approx(3.5)  # (5+2+4+3)/4
        assert stats.quality.ratings_count == 4
        assert stats.ai_chat.escalated_count == 3  # t1, t3, t6 (AI_CHAT)
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
