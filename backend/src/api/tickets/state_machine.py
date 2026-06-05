"""Машина состояний статусов заявки (ТЗ §3.2).

Разрешённые переходы заданы таблицей; запрещённые отклоняются вызывающим кодом
с 422 (проза ТЗ §3.2 + схема `TicketUpdate` контракта + DoD Issue #8; одиночное
«409» в описании операции PATCH — внутренняя нестыковка контракта, к выверке в
production-spec #11). Каждый фактический переход фиксируется в TicketHistory (§3.7).
"""

from __future__ import annotations

from api.tickets.enums import TicketStatus

# Из какого статуса в какие разрешён переход (набор Issue #8).
ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.NEW: frozenset({TicketStatus.OPEN, TicketStatus.CLOSED}),
    TicketStatus.OPEN: frozenset(
        {TicketStatus.PENDING, TicketStatus.WAITING, TicketStatus.ESCALATED, TicketStatus.RESOLVED}
    ),
    TicketStatus.PENDING: frozenset(
        {TicketStatus.OPEN, TicketStatus.WAITING, TicketStatus.ESCALATED, TicketStatus.RESOLVED}
    ),
    TicketStatus.WAITING: frozenset(
        {TicketStatus.OPEN, TicketStatus.PENDING, TicketStatus.ESCALATED, TicketStatus.RESOLVED}
    ),
    TicketStatus.ESCALATED: frozenset(
        {TicketStatus.OPEN, TicketStatus.PENDING, TicketStatus.WAITING, TicketStatus.RESOLVED}
    ),
    TicketStatus.RESOLVED: frozenset({TicketStatus.CLOSED, TicketStatus.REOPENED}),
    TicketStatus.CLOSED: frozenset({TicketStatus.REOPENED}),
    TicketStatus.REOPENED: frozenset(
        {
            TicketStatus.OPEN,
            TicketStatus.PENDING,
            TicketStatus.WAITING,
            TicketStatus.ESCALATED,
            TicketStatus.RESOLVED,
        }
    ),
}


def is_allowed_transition(current: TicketStatus, target: TicketStatus) -> bool:
    """Разрешён ли переход current→target. Идемпотентный no-op (cur==target) — да."""
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


# Терминальные статусы — ЕДИНЫЙ источник (ADR-0008 Решение 5): «активная заявка» =
# заявка в НЕ-терминальном статусе. На E5 терминальны RESOLVED и CLOSED (из них
# работа не идёт; REOPENED — снова активна). Канон в enum-объектах TicketStatus;
# для live-query, где `Ticket.status` строковый (String(32)), брать строковую
# проекцию `[s.value for s in TERMINAL_STATUSES]` локально — НЕ подставлять frozenset
# enum'ов в `.notin_()`. Существующие дубли (sla/worker/scan.py, _RATEABLE_STATUSES)
# развязываются на этот канон в TODO(#118), вне scope #109.
TERMINAL_STATUSES: frozenset[TicketStatus] = frozenset({TicketStatus.RESOLVED, TicketStatus.CLOSED})


def is_terminal(status: TicketStatus) -> bool:
    """Терминален ли статус (из него заявка не считается активной). См. TERMINAL_STATUSES."""
    return status in TERMINAL_STATUSES
