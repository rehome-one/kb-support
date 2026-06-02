"""Unit-тесты калькулятора SLA-дедлайнов (#87): точные timestamp'ы, рабочие часы, DST."""

from __future__ import annotations

import datetime
from typing import Any

from api.sla.calculator import compute_due_at
from api.sla.models import BusinessHours

UTC = datetime.UTC


def _bh(timezone: str, schedule: dict[str, Any]) -> BusinessHours:
    return BusinessHours(name="bh", timezone=timezone, schedule=schedule)


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, tzinfo=UTC)


# Берлин зимой = UTC+1 (январь 2026).
_BERLIN_WEEK = {d: [["09:00", "18:00"]] for d in ("mon", "tue", "wed", "thu", "fri")}


def test_24x7_is_wall_clock() -> None:
    start = _utc(2026, 1, 5, 10, 0)
    assert compute_due_at(start, 90, None) == start + datetime.timedelta(minutes=90)


def test_within_single_working_day() -> None:
    bh = _bh("Europe/Berlin", _BERLIN_WEEK)
    # Пн 2026-01-05 10:00 Berlin = 09:00 UTC. +60 рабочих минут → 11:00 Berlin = 10:00 UTC.
    start = _utc(2026, 1, 5, 9, 0)
    assert compute_due_at(start, 60, bh) == _utc(2026, 1, 5, 10, 0)


def test_close_boundary_is_reachable_and_exclusive() -> None:
    bh = _bh("Europe/Berlin", {"mon": [["09:00", "17:00"]]})
    # Старт Пн 16:30 Berlin (15:30 UTC), +30 мин → ровно 17:00 Berlin (16:00 UTC), граница close.
    start = _utc(2026, 1, 5, 15, 30)
    assert compute_due_at(start, 30, bh) == _utc(2026, 1, 5, 16, 0)


def test_spills_to_next_working_day() -> None:
    bh = _bh("Europe/Berlin", _BERLIN_WEEK)
    # Пн 17:30 Berlin (16:30 UTC), осталось до 18:00 = 30 мин; +60 → 30 мин Пн + 30 мин Вт.
    start = _utc(2026, 1, 5, 16, 30)
    # Вт 09:30 Berlin = 08:30 UTC.
    assert compute_due_at(start, 60, bh) == _utc(2026, 1, 6, 8, 30)


def test_crosses_weekend() -> None:
    bh = _bh("Europe/Berlin", _BERLIN_WEEK)
    # Пт 2026-01-09 17:30 Berlin (16:30 UTC): 30 мин до 18:00, остаток 30 мин → Пн 09:30.
    start = _utc(2026, 1, 9, 16, 30)
    # Пн 2026-01-12 09:30 Berlin = 08:30 UTC.
    assert compute_due_at(start, 60, bh) == _utc(2026, 1, 12, 8, 30)


def test_start_before_window() -> None:
    bh = _bh("Europe/Berlin", _BERLIN_WEEK)
    # Пн 07:00 Berlin (06:00 UTC) — до открытия; отсчёт с 09:00, +60 → 10:00 Berlin (09:00 UTC).
    start = _utc(2026, 1, 5, 6, 0)
    assert compute_due_at(start, 60, bh) == _utc(2026, 1, 5, 9, 0)


def test_start_on_weekend() -> None:
    bh = _bh("Europe/Berlin", _BERLIN_WEEK)
    # Сб 2026-01-10 12:00 Berlin (11:00 UTC) — выходной; отсчёт с Пн 09:00, +60 → 10:00 Berlin.
    start = _utc(2026, 1, 10, 11, 0)
    assert compute_due_at(start, 60, bh) == _utc(2026, 1, 12, 9, 0)


def test_multi_interval_lunch_break() -> None:
    bh = _bh("Europe/Berlin", {"mon": [["09:00", "13:00"], ["14:00", "18:00"]]})
    # Пн 12:30 Berlin (11:30 UTC): 30 мин до 13:00, остаток 30 → возобновление 14:00 → 14:30.
    start = _utc(2026, 1, 5, 11, 30)
    # 14:30 Berlin = 13:30 UTC.
    assert compute_due_at(start, 60, bh) == _utc(2026, 1, 5, 13, 30)


def test_empty_schedule_returns_none() -> None:
    bh = _bh("Europe/Berlin", {})
    assert compute_due_at(_utc(2026, 1, 5, 9, 0), 60, bh) is None


def test_all_days_off_returns_none() -> None:
    bh = _bh("Europe/Berlin", {"mon": [], "tue": []})
    assert compute_due_at(_utc(2026, 1, 5, 9, 0), 60, bh) is None


def test_dst_spring_forward_uses_real_duration() -> None:
    # Берлин spring-forward: 2026-03-29 (вс), 02:00→03:00 (потеря часа).
    # Окно вс 00:00–06:00 по СТЕНЕ = 5 реальных часов (300 мин) из-за перехода.
    bh = _bh("Europe/Berlin", {"sun": [["00:00", "06:00"]]})
    # Старт вс 00:00 Berlin = 2026-03-28 23:00 UTC (ещё UTC+1).
    start = datetime.datetime(2026, 3, 28, 23, 0, tzinfo=UTC)
    # 300 рабочих минут заполняют всё окно → due = 06:00 Berlin = 04:00 UTC (уже UTC+2).
    assert compute_due_at(start, 300, bh) == _utc(2026, 3, 29, 4, 0)
    # 240 мин (4 реальных часа): 23:00 UTC + 4ч = 03:00 UTC = 05:00 Berlin.
    assert compute_due_at(start, 240, bh) == _utc(2026, 3, 29, 3, 0)
