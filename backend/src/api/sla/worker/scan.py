"""Скан SLA-дедлайнов + эскалация через хук (E4-6, #90).

`escalate` — чистая логика над списком заявок (unit-тест без БД). `scan_and_escalate`
добавляет выборку из БД. Источник истины — БД (NFR-3.2): воркер не держит расписание
в памяти, а сканирует по `*_due_at` → переживает перезапуск.

breach считается теми же предикатами, что и read-side (#89): SQL — через
`api.tickets.sla_query`, per-ticket флаги — через `is_resolution_breached` /
`is_first_response_breached`. Никакого второго источника правды (ADR-0007 Решение 1).
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterable

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.observability.logging import get_logger
from api.sla.worker.hooks import BreachHook, SlaBreachEvent
from api.tickets.enums import TicketStatus
from api.tickets.models import Ticket
from api.tickets.sla_query import (
    first_response_breached_clause,
    payout_breached_clause,
    resolution_breached_clause,
)
from api.tickets.sla_state import (
    is_first_response_breached,
    is_payout_breached,
    is_resolution_breached,
)

_logger = get_logger("sla.worker")

# Терминальные статусы: заявка уже не требует проактивной эскалации.
_TERMINAL_STATUSES = (TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value)

# Seam дедупа: True → заявку пропустить (уже обработана). E4 — инертный дефолт;
# реальный маркер «уже эскалирована» — E5/#18 (вместе с действиями эскалации).
AlreadyHandled = Callable[[Ticket], bool]


def _never_handled(_ticket: Ticket) -> bool:
    """Дефолтный seam: ничего не отфильтровано (E4 инертен, дедуп — E5/#18)."""
    return False


def select_due_tickets(now: datetime.datetime, *, batch_limit: int) -> Select[tuple[Ticket]]:
    """Активные заявки с нарушенным дедлайном (любая нога). Детерминированный порядок.

    Сортировка по ранней из двух ног (`LEAST` игнорирует NULL): иначе заявки с
    first-response-only breach (resolution_due_at = NULL) уходили бы в хвост NULLS LAST
    и систематически вытеснялись бы за `batch_limit`.
    """
    return (
        select(Ticket)
        .where(
            Ticket.status.notin_(_TERMINAL_STATUSES),
            or_(
                resolution_breached_clause(now),
                first_response_breached_clause(now),
                payout_breached_clause(now),
            ),
        )
        .order_by(
            # LEAST игнорирует NULL (Postgres) — payout-only breach не вытесняется за batch_limit.
            func.least(
                Ticket.resolution_due_at,
                Ticket.first_response_due_at,
                Ticket.payout_due_at,
            ).asc(),
            Ticket.id.asc(),
        )
        .limit(batch_limit)
    )


def _build_event(ticket: Ticket, now: datetime.datetime) -> SlaBreachEvent:
    return SlaBreachEvent(
        ticket_id=ticket.id,
        number=ticket.number,
        type=ticket.type,
        priority=ticket.priority,
        team=ticket.team,
        first_response_breached=is_first_response_breached(
            now,
            first_response_due_at=ticket.first_response_due_at,
            first_responded_at=ticket.first_responded_at,
        ),
        resolution_breached=is_resolution_breached(
            now,
            resolution_due_at=ticket.resolution_due_at,
            resolved_at=ticket.resolved_at,
            sla_paused_at=ticket.sla_paused_at,
        ),
        payout_breached=is_payout_breached(
            now,
            case_state=ticket.case_state,
            payout_due_at=ticket.payout_due_at,
        ),
    )


async def escalate(
    tickets: Iterable[Ticket],
    now: datetime.datetime,
    *,
    hook: BreachHook,
    already_handled: AlreadyHandled = _never_handled,
) -> list[SlaBreachEvent]:
    """Для каждой не-обработанной заявки построить событие и дёрнуть хук."""
    events: list[SlaBreachEvent] = []
    for ticket in tickets:
        if already_handled(ticket):
            continue
        event = _build_event(ticket, now)
        await hook(event)
        events.append(event)
    return events


async def scan_and_escalate(
    session: AsyncSession,
    *,
    now: datetime.datetime,
    hook: BreachHook,
    batch_limit: int,
    already_handled: AlreadyHandled = _never_handled,
) -> list[SlaBreachEvent]:
    """Выбрать заявки с просроченными дедлайнами из БД и эскалировать каждую."""
    result = await session.execute(select_due_tickets(now, batch_limit=batch_limit))
    rows = list(result.scalars().all())
    if len(rows) == batch_limit:
        # No silent caps: проход насыщён, часть просроченных заявок отложена до
        # следующего скана. Сигнализируем, чтобы усечение не выглядело «всё покрыто».
        _logger.warning("sla_scan batch saturated limit=%s — остаток отложен", batch_limit)
    return await escalate(rows, now, hook=hook, already_handled=already_handled)
