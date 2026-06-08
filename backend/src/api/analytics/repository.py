"""SQL-агрегаты аналитики по своей БД (E8-1, #165).

Считает секции `SupportStats` GROUP BY / AVG / COUNT поверх `AsyncSession` (эталон
стиля — `sla/repository.py`). Переиспользует единый breach-предикат `tickets/sla_query`
(#90) и канон терминальности `state_machine.TERMINAL_STATUSES` (#109) — никаких
локальных дублей семантики.

**Якоря периода (ADR-0011 Решение 4):**
- volume (`total`/`resolved`/`closed`/`by_type`/`by_channel`/`escalated`/`quality`/
  `reopened_rate`) — по `created_at ∈ [start, end_exclusive)`;
- `open` — СНАПШОТ (решение Архитектора): `status ∉ TERMINAL`, без границ периода;
- `*_compliance` — по когорте «завершившихся в периоде» (`first_responded_at` /
  `resolved_at ∈ period`);
- `breaches` — по когорте created-в-периоде на момент `now` (см. docstring `sla_stats`).

**Арх-константа:** читается ТОЛЬКО таблица `tickets` своей БД (NFR-4.4, ADR-0011 Реш.2).
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from api.analytics.dto import (
    PerformanceStats,
    QualityStats,
    SlaStats,
    TicketCounts,
)
from api.analytics.period import StatsPeriod
from api.tickets.enums import TicketChannel, TicketStatus
from api.tickets.models import Ticket
from api.tickets.sla_query import first_response_breached_clause, resolution_breached_clause
from api.tickets.state_machine import TERMINAL_STATUSES

# Проекция значений терминальных статусов для SQL (state_machine.py предписывает НЕ
# подставлять frozenset Enum-объектов в запрос — только их строковые `.value`).
_TERMINAL_VALUES = [status.value for status in TERMINAL_STATUSES]


def _pct(numerator: int, denominator: int) -> float | None:
    """Процент с инвариантом нулевого знаменателя (ADR-0011 Реш.4): 0 знаменатель → None."""
    if denominator == 0:
        return None
    return 100.0 * numerator / denominator


def _as_float(value: Any) -> float | None:
    """AVG() из БД (Decimal/None) → float | None (None при пустой выборке)."""
    if value is None:
        return None
    return float(value)


def _avg_minutes(
    end_col: InstrumentedAttribute[datetime.datetime | None],
    start_col: InstrumentedAttribute[datetime.datetime],
) -> ColumnElement[float]:
    """SQL: средняя длительность `end − start` в минутах (wall-clock, UTC)."""
    return func.avg(func.extract("epoch", end_col - start_col) / 60.0)


class AnalyticsRepository:
    """Агрегаты сводных метрик поверх `AsyncSession`. Только чтение."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _created_in_period(self, period: StatsPeriod) -> ColumnElement[bool]:
        return and_(
            Ticket.created_at >= period.start,
            Ticket.created_at < period.end_exclusive,
        )

    async def ticket_counts(self, period: StatsPeriod) -> TicketCounts:
        """Объёмы: когортные total/resolved/closed/by_* + снапшот `open` (см. docstring DTO).

        Инвариант `open + resolved + closed = total` НАМЕРЕННО не держится (open — снапшот,
        остальное — когорта). Equality в тестах не ассертить.
        """
        in_period = self._created_in_period(period)
        cohort_stmt = select(
            func.count(),
            func.coalesce(
                func.sum(case((Ticket.status == TicketStatus.RESOLVED.value, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Ticket.status == TicketStatus.CLOSED.value, 1), else_=0)), 0
            ),
        ).where(in_period)
        total_raw, resolved_raw, closed_raw = (await self._session.execute(cohort_stmt)).one()

        by_type = await self._group_counts(Ticket.type, in_period)
        by_channel = await self._group_counts(Ticket.channel, in_period)

        # open — снапшот: сколько открыто СЕЙЧАС (без фильтра периода).
        open_raw = (
            await self._session.execute(
                select(func.count()).where(Ticket.status.not_in(_TERMINAL_VALUES))
            )
        ).scalar_one()

        return TicketCounts(
            total=int(total_raw),
            open=int(open_raw),
            resolved=int(resolved_raw),
            closed=int(closed_raw),
            by_type=by_type,
            by_channel=by_channel,
        )

    async def _group_counts(
        self, column: InstrumentedAttribute[str], where_clause: ColumnElement[bool]
    ) -> dict[str, int]:
        stmt = select(column, func.count()).where(where_clause).group_by(column)
        rows = (await self._session.execute(stmt)).all()
        return {str(key): int(count) for key, count in rows}

    async def sla_stats(self, period: StatsPeriod, now: datetime.datetime) -> SlaStats:
        """Соблюдение SLA.

        compliance: по заявкам, завершившим ногу В ПЕРИОДЕ, с проставленным дедлайном —
        доля уложившихся **СТРОГО до дедлайна** (`completed_at < due_at`). Строгое `<`,
        а не `<=`, — согласование с breach-каноном #89/#90 (`as_of >= due_at` = нарушение):
        met ⇔ ¬breach, заявка ровно НА дедлайне считается нарушенной, не уложившейся (иначе
        граничная заявка была бы одновременно «met» и «breached»). `resolution_due_at` УЖЕ
        pause-adjusted (#88, `sla_pause.py`): сравниваем РОВНО с ним, БЕЗ повторного
        вычитания `sla_paused_seconds` (условие 3 ревью #165 — иначе двойной учёт пауз).

        breaches: заявки, СОЗДАННЫЕ в периоде и нарушенные на момент `now` (единый
        предикат #90). **`breaches` не обязан совпадать с `(1 − compliance)·N`** — у них
        разные якоря: просроченная, но ещё не завершённая заявка входит в `breaches`, но
        не в знаменатель compliance. `breaches` дрейфует со временем (зависит от `now`).
        """
        fr_where = and_(
            Ticket.first_responded_at >= period.start,
            Ticket.first_responded_at < period.end_exclusive,
            Ticket.first_response_due_at.is_not(None),
        )
        fr_total, fr_met = (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.sum(
                            case(
                                (Ticket.first_responded_at < Ticket.first_response_due_at, 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(fr_where)
            )
        ).one()

        res_where = and_(
            Ticket.resolved_at >= period.start,
            Ticket.resolved_at < period.end_exclusive,
            Ticket.resolution_due_at.is_not(None),
        )
        res_total, res_met = (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.sum(case((Ticket.resolved_at < Ticket.resolution_due_at, 1), else_=0)),
                        0,
                    ),
                ).where(res_where)
            )
        ).one()

        breach_where = and_(
            self._created_in_period(period),
            or_(resolution_breached_clause(now), first_response_breached_clause(now)),
        )
        breaches = (
            await self._session.execute(select(func.count()).where(breach_where))
        ).scalar_one()

        return SlaStats(
            first_response_compliance_pct=_pct(int(fr_met), int(fr_total)),
            resolution_compliance_pct=_pct(int(res_met), int(res_total)),
            breaches=int(breaches),
        )

    async def performance_stats(self, period: StatsPeriod) -> PerformanceStats:
        """Среднее время первого ответа/решения (wall-clock) + доля переоткрытий.

        avg_*_minutes — wall-clock, НЕ pause-adjusted (условие 2 ревью #165; pause-adjusted
        TTR — у `sla_metrics` #91 для Grafana). avg_first_response = «время в очереди» FR-7.3.
        """
        avg_fr = (
            await self._session.execute(
                select(_avg_minutes(Ticket.first_responded_at, Ticket.created_at)).where(
                    and_(
                        Ticket.first_responded_at >= period.start,
                        Ticket.first_responded_at < period.end_exclusive,
                    )
                )
            )
        ).scalar_one()
        avg_res = (
            await self._session.execute(
                select(_avg_minutes(Ticket.resolved_at, Ticket.created_at)).where(
                    and_(
                        Ticket.resolved_at >= period.start,
                        Ticket.resolved_at < period.end_exclusive,
                    )
                )
            )
        ).scalar_one()

        reopened_total, reopened = (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(case((Ticket.reopened_count > 0, 1), else_=0)), 0),
                ).where(self._created_in_period(period))
            )
        ).one()

        return PerformanceStats(
            avg_first_response_minutes=_as_float(avg_fr),
            avg_resolution_minutes=_as_float(avg_res),
            reopened_rate_pct=_pct(int(reopened), int(reopened_total)),
        )

    async def quality_stats(self, period: StatsPeriod) -> QualityStats:
        """Средняя оценка и число оценок по заявкам, созданным в периоде (rating IS NOT NULL).

        ФЗ-152: читается только числовой `rating`, НЕ `rating_comment`.
        """
        avg_rating, count = (
            await self._session.execute(
                select(func.avg(Ticket.rating), func.count()).where(
                    and_(self._created_in_period(period), Ticket.rating.is_not(None))
                )
            )
        ).one()
        return QualityStats(avg_rating=_as_float(avg_rating), ratings_count=int(count))

    async def ai_chat_escalated(self, period: StatsPeriod) -> int:
        """Число заявок `channel=AI_CHAT`, созданных в периоде (эскалации из kb-search)."""
        escalated = (
            await self._session.execute(
                select(func.count()).where(
                    and_(
                        self._created_in_period(period),
                        Ticket.channel == TicketChannel.AI_CHAT.value,
                    )
                )
            )
        ).scalar_one()
        return int(escalated)
