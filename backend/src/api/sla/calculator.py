"""Калькулятор SLA-дедлайнов с учётом рабочих часов (E4-3 #87, FR-4.2).

Чистая функция без I/O. Дедлайн = `start` + N **рабочих** минут по недельному
графику `BusinessHours` (интервалы локального времени + IANA-TZ). `business_hours
=None` → круглосуточно (24/7): `start + N` wall-clock.

**Корректность TZ/DST.** Дни недели и границы интервалов берутся в локальной TZ
графика (`zoneinfo`), но накопление длительности и итоговый дедлайн считаются в UTC
(`astimezone(UTC)`), поэтому переходы DST не приводят к двойному учёту/пропуску.

**Защита от бесконечности.** Если у графика нет рабочих интервалов (пустой/все дни
выходные) либо дедлайн не уложился в горизонт сканирования — возвращаем `None` (SLA
не определён) + WARN, без исключения и без вечного цикла.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from api.observability.logging import get_logger
from api.sla.models import BusinessHours
from api.sla.schemas import WEEKDAYS

_logger = get_logger("sla.calculator")

# Горизонт сканирования рабочих окон: дальше дедлайн считаем неопределимым
# (защита от пустого/некорректного графика без рабочей ёмкости).
_SCAN_HORIZON_DAYS = 366


def _day_intervals(
    schedule: dict[str, object], weekday_index: int
) -> list[tuple[datetime.time, datetime.time]]:
    """Интервалы `(open, close)` для дня недели (0=пн) из нормализованного графика."""
    raw = schedule.get(WEEKDAYS[weekday_index])
    if not isinstance(raw, list):
        return []
    intervals: list[tuple[datetime.time, datetime.time]] = []
    for pair in raw:
        if isinstance(pair, list | tuple) and len(pair) == 2:
            intervals.append(
                (datetime.time.fromisoformat(pair[0]), datetime.time.fromisoformat(pair[1]))
            )
    return intervals


def compute_due_at(
    start: datetime.datetime, minutes: int, business_hours: BusinessHours | None
) -> datetime.datetime | None:
    """Дедлайн через `minutes` рабочих минут от `start` (tz-aware UTC) либо `None`.

    `business_hours=None` → 24/7. Иначе — арифметика рабочих часов по графику.
    """
    if business_hours is None:
        return start + datetime.timedelta(minutes=minutes)

    tz = ZoneInfo(business_hours.timezone)
    schedule = business_hours.schedule
    remaining = datetime.timedelta(minutes=minutes)
    cursor_local = start.astimezone(tz)
    horizon = cursor_local + datetime.timedelta(days=_SCAN_HORIZON_DAYS)

    while cursor_local <= horizon:
        for open_t, close_t in _day_intervals(schedule, cursor_local.weekday()):
            interval_start = datetime.datetime.combine(cursor_local.date(), open_t, tzinfo=tz)
            interval_end = datetime.datetime.combine(cursor_local.date(), close_t, tzinfo=tz)
            eff_start = max(cursor_local, interval_start)
            if eff_start >= interval_end:
                continue
            # Длительность считаем в UTC — корректно через переходы DST.
            available = interval_end.astimezone(datetime.UTC) - eff_start.astimezone(datetime.UTC)
            if remaining <= available:
                return eff_start.astimezone(datetime.UTC) + remaining
            remaining -= available
            cursor_local = interval_end
        # Следующий день с начала суток (локально).
        next_day = cursor_local.date() + datetime.timedelta(days=1)
        cursor_local = datetime.datetime.combine(next_day, datetime.time(0, 0), tzinfo=tz)

    _logger.warning(
        "sla due undefined: no working capacity in horizon (business_hours_id=%s, days=%s)",
        business_hours.id,
        _SCAN_HORIZON_DAYS,
    )
    return None
