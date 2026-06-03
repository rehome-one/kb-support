"""Unit-тесты учёта пауз SLA (#88): сдвиг resolution_due_at на время PENDING/WAITING."""

from __future__ import annotations

import datetime

from api.tickets.enums import TicketStatus
from api.tickets.models import Ticket
from api.tickets.sla_pause import apply_pause_accounting

UTC = datetime.UTC
_T0 = datetime.datetime(2026, 6, 3, 9, 0, tzinfo=UTC)
_DUE = datetime.datetime(2026, 6, 3, 17, 0, tzinfo=UTC)
_FR_DUE = datetime.datetime(2026, 6, 3, 10, 0, tzinfo=UTC)


def _ticket(
    status: TicketStatus,
    *,
    paused_at: datetime.datetime | None = None,
    paused_seconds: int = 0,
    resolution_due_at: datetime.datetime | None = _DUE,
    first_response_due_at: datetime.datetime | None = _FR_DUE,
) -> Ticket:
    ticket = Ticket()
    ticket.status = status.value
    ticket.sla_paused_at = paused_at
    ticket.sla_paused_seconds = paused_seconds
    ticket.resolution_due_at = resolution_due_at
    ticket.first_response_due_at = first_response_due_at
    return ticket


def test_enter_pause_records_start_no_shift() -> None:
    t = _ticket(TicketStatus.PENDING)
    apply_pause_accounting(t, TicketStatus.OPEN.value, _T0)
    assert t.sla_paused_at == _T0
    assert t.resolution_due_at == _DUE  # дедлайн ещё не сдвинут
    assert t.first_response_due_at == _FR_DUE
    assert t.sla_paused_seconds == 0


def test_exit_pause_shifts_resolution_by_pause_duration() -> None:
    t = _ticket(TicketStatus.OPEN, paused_at=_T0)
    now = _T0 + datetime.timedelta(hours=1)
    apply_pause_accounting(t, TicketStatus.PENDING.value, now)
    assert t.resolution_due_at == _DUE + datetime.timedelta(hours=1)
    assert t.sla_paused_seconds == 3600
    assert t.sla_paused_at is None
    assert t.first_response_due_at == _FR_DUE  # первый ответ паузами не двигается


def test_pending_to_waiting_keeps_pause_running() -> None:
    t = _ticket(TicketStatus.WAITING, paused_at=_T0)
    apply_pause_accounting(t, TicketStatus.PENDING.value, _T0 + datetime.timedelta(minutes=30))
    assert t.sla_paused_at == _T0  # пауза продолжается, начало не сброшено
    assert t.resolution_due_at == _DUE  # сдвига нет
    assert t.sla_paused_seconds == 0


def test_continuous_pause_through_waiting_counted_once() -> None:
    # OPEN→PENDING→WAITING→OPEN: вся непрерывная пауза учитывается одним span'ом.
    t = _ticket(TicketStatus.PENDING)
    apply_pause_accounting(t, TicketStatus.OPEN.value, _T0)  # вход
    apply_pause_accounting(  # PENDING→WAITING: продолжение
        _set_status(t, TicketStatus.WAITING), TicketStatus.PENDING.value, _T0 + _mins(20)
    )
    apply_pause_accounting(  # выход WAITING→OPEN через 60 мин от начала
        _set_status(t, TicketStatus.OPEN), TicketStatus.WAITING.value, _T0 + _mins(60)
    )
    assert t.resolution_due_at == _DUE + _mins(60)
    assert t.sla_paused_seconds == 3600
    assert t.sla_paused_at is None


def test_two_separate_pauses_accumulate() -> None:
    # OPEN→PENDING→OPEN→WAITING→OPEN: суммарный сдвиг = сумма двух пауз.
    t = _ticket(TicketStatus.PENDING)
    apply_pause_accounting(t, TicketStatus.OPEN.value, _T0)
    apply_pause_accounting(
        _set_status(t, TicketStatus.OPEN), TicketStatus.PENDING.value, _T0 + _mins(15)
    )
    apply_pause_accounting(
        _set_status(t, TicketStatus.WAITING), TicketStatus.OPEN.value, _T0 + _mins(20)
    )
    apply_pause_accounting(
        _set_status(t, TicketStatus.OPEN), TicketStatus.WAITING.value, _T0 + _mins(50)
    )
    # Паузы: 15 мин + 30 мин = 45 мин.
    assert t.resolution_due_at == _DUE + _mins(45)
    assert t.sla_paused_seconds == 45 * 60
    assert t.sla_paused_at is None


def test_exit_pause_into_resolved_still_shifts() -> None:
    # PENDING→RESOLVED: RESOLVED — не пауза, выход срабатывает (сдвиг + очистка).
    t = _ticket(TicketStatus.RESOLVED, paused_at=_T0)
    apply_pause_accounting(t, TicketStatus.PENDING.value, _T0 + _mins(10))
    assert t.resolution_due_at == _DUE + _mins(10)
    assert t.sla_paused_at is None
    assert t.sla_paused_seconds == 600


def test_exit_pause_into_escalated_shifts() -> None:
    # PENDING→ESCALATED: ESCALATED — активная работа, не пауза → выход срабатывает.
    t = _ticket(TicketStatus.ESCALATED, paused_at=_T0)
    apply_pause_accounting(t, TicketStatus.PENDING.value, _T0 + _mins(10))
    assert t.resolution_due_at == _DUE + _mins(10)
    assert t.sla_paused_at is None


def test_escalated_is_not_a_pause() -> None:
    # OPEN→ESCALATED→OPEN: ESCALATED не пауза — ничего не меняется.
    t = _ticket(TicketStatus.ESCALATED)
    apply_pause_accounting(t, TicketStatus.OPEN.value, _T0)
    assert t.sla_paused_at is None
    assert t.resolution_due_at == _DUE
    apply_pause_accounting(
        _set_status(t, TicketStatus.OPEN), TicketStatus.ESCALATED.value, _T0 + _mins(30)
    )
    assert t.resolution_due_at == _DUE


def test_exit_pause_without_resolution_due_at_only_accumulates() -> None:
    # Нет SLA (resolution_due_at=None): сдвигать нечего, но paused_seconds копится.
    t = _ticket(TicketStatus.OPEN, paused_at=_T0, resolution_due_at=None)
    apply_pause_accounting(t, TicketStatus.PENDING.value, _T0 + _mins(5))
    assert t.resolution_due_at is None
    assert t.sla_paused_seconds == 300
    assert t.sla_paused_at is None


def _set_status(ticket: Ticket, status: TicketStatus) -> Ticket:
    ticket.status = status.value
    return ticket


def _mins(n: int) -> datetime.timedelta:
    return datetime.timedelta(minutes=n)
