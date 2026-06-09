"""Unit-тесты сроков претензий по Договору (E10-6 #196) — чистые функции, без БД."""

from __future__ import annotations

import datetime

from api.tickets.claims_sla import (
    compute_payout_due_at,
    compute_regress_due_at,
    compute_review_due_at,
)
from api.tickets.enums import TicketCaseState
from api.tickets.sla_state import is_payout_breached

UTC = datetime.UTC


def test_review_due_at_is_30_calendar_days() -> None:
    anchor = datetime.datetime(2026, 1, 1, 10, 30, tzinfo=UTC)
    assert compute_review_due_at(anchor) == anchor + datetime.timedelta(days=30)


def test_regress_due_at_is_14_calendar_days() -> None:
    anchor = datetime.datetime(2026, 1, 1, 10, 30, tzinfo=UTC)
    assert compute_regress_due_at(anchor) == anchor + datetime.timedelta(days=14)


def test_payout_from_monday_is_two_weeks_later() -> None:
    # 2026-01-05 — понедельник; 10 рабочих дней = ровно 2 недели → пн 2026-01-19.
    monday = datetime.datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    assert monday.weekday() == 0
    due = compute_payout_due_at(monday)
    assert due == datetime.datetime(2026, 1, 19, 14, 0, tzinfo=UTC)


def test_payout_from_friday_skips_weekends() -> None:
    # 2026-01-02 — пятница; 10 рабочих дней (пропуск Сб/Вс) → пт 2026-01-16.
    friday = datetime.datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    assert friday.weekday() == 4
    due = compute_payout_due_at(friday)
    assert due == datetime.datetime(2026, 1, 16, 9, 0, tzinfo=UTC)


def test_payout_always_lands_on_weekday_and_preserves_time() -> None:
    for day in range(1, 8):  # любой день недели как якорь
        anchor = datetime.datetime(2026, 6, day, 8, 15, tzinfo=UTC)
        due = compute_payout_due_at(anchor)
        assert due.weekday() < 5  # Пн–Пт
        assert (due.hour, due.minute) == (8, 15)  # время суток сохранено


_NOW = datetime.datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
_PAST = _NOW - datetime.timedelta(hours=1)
_FUTURE = _NOW + datetime.timedelta(hours=1)


def test_payout_breached_true_when_overdue_in_payout_pending() -> None:
    assert is_payout_breached(
        _NOW, case_state=TicketCaseState.PAYOUT_PENDING.value, payout_due_at=_PAST
    )


def test_payout_not_breached_before_deadline() -> None:
    assert not is_payout_breached(
        _NOW, case_state=TicketCaseState.PAYOUT_PENDING.value, payout_due_at=_FUTURE
    )


def test_payout_not_breached_when_not_in_payout_pending() -> None:
    # Уже выплачено (PAID) — срок не «висит», даже если payout_due_at в прошлом.
    assert not is_payout_breached(_NOW, case_state=TicketCaseState.PAID.value, payout_due_at=_PAST)


def test_payout_not_breached_without_deadline() -> None:
    assert not is_payout_breached(
        _NOW, case_state=TicketCaseState.PAYOUT_PENDING.value, payout_due_at=None
    )
