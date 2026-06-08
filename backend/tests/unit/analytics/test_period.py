"""Unit-тесты модели периода аналитики (E8-1, #165). Чистые, без БД."""

from __future__ import annotations

import datetime

import pytest

from api.analytics.period import PeriodError, StatsPeriod, resolve_period

_TODAY = datetime.date(2026, 6, 8)
_UTC = datetime.UTC


def test_default_window_is_last_30_days() -> None:
    period = resolve_period(None, None, today=_TODAY)
    assert period.to_date == _TODAY
    assert period.from_date == datetime.date(2026, 5, 9)  # 30 дней назад


def test_default_from_anchored_on_explicit_to() -> None:
    period = resolve_period(None, datetime.date(2026, 1, 31), today=_TODAY)
    assert period.to_date == datetime.date(2026, 1, 31)
    assert period.from_date == datetime.date(2026, 1, 1)


def test_default_to_is_today_when_only_from_given() -> None:
    period = resolve_period(datetime.date(2026, 6, 1), None, today=_TODAY)
    assert period.from_date == datetime.date(2026, 6, 1)
    assert period.to_date == _TODAY


def test_utc_bounds_are_half_open_interval() -> None:
    period = StatsPeriod(from_date=datetime.date(2026, 1, 10), to_date=datetime.date(2026, 1, 20))
    assert period.start == datetime.datetime(2026, 1, 10, 0, 0, 0, tzinfo=_UTC)
    # to включительно ⇒ эксклюзивная граница = начало СЛЕДУЮЩЕГО дня после to.
    assert period.end_exclusive == datetime.datetime(2026, 1, 21, 0, 0, 0, tzinfo=_UTC)


def test_single_day_period_spans_full_utc_day() -> None:
    period = StatsPeriod(from_date=datetime.date(2026, 1, 10), to_date=datetime.date(2026, 1, 10))
    assert period.start == datetime.datetime(2026, 1, 10, 0, 0, 0, tzinfo=_UTC)
    assert period.end_exclusive == datetime.datetime(2026, 1, 11, 0, 0, 0, tzinfo=_UTC)


def test_from_after_to_raises() -> None:
    with pytest.raises(PeriodError):
        resolve_period(datetime.date(2026, 2, 1), datetime.date(2026, 1, 1), today=_TODAY)


def test_equal_from_to_is_valid() -> None:
    period = resolve_period(datetime.date(2026, 1, 5), datetime.date(2026, 1, 5), today=_TODAY)
    assert period.from_date == period.to_date == datetime.date(2026, 1, 5)
