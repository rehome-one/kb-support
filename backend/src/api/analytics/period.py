"""Период агрегации аналитики (E8-1, #165).

ADR-0011 Решение 4: агрегация в **UTC**, границы суток в UTC, `from`/`to`
**включительно**; при отсутствии `from`/`to` — окно `[today − 30 дней; today]`
(дефолт). Невалидный период (`from > to`) → `PeriodError` (роутер #166 → 422).

Модуль чистый (без I/O): `today` инжектируется вызывающим — детерминизм тестов и
независимость от системных часов.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

_DEFAULT_WINDOW_DAYS = 30


class PeriodError(ValueError):
    """`from > to` — невалидный период. Роутер (#166) транслирует в 422."""


@dataclass(frozen=True)
class StatsPeriod:
    """Разрешённый период агрегации. `from_date`/`to_date` — включительные даты (UTC).

    SQL-фильтр по периоду — полуинтервал `[start, end_exclusive)` (NIT-3 ревью #165:
    полуинтервал надёжнее, чем `<= 23:59:59.999999` — не теряет записи в последнюю
    микросекунду и не зависит от точности timestamp).
    """

    from_date: datetime.date
    to_date: datetime.date

    @property
    def start(self) -> datetime.datetime:
        """Начало периода — `00:00:00 UTC` даты `from_date` (включительно)."""
        return datetime.datetime.combine(self.from_date, datetime.time.min, tzinfo=datetime.UTC)

    @property
    def end_exclusive(self) -> datetime.datetime:
        """Эксклюзивная верхняя граница — `00:00:00 UTC` дня ПОСЛЕ `to_date`.

        Полуинтервал `[start, end_exclusive)` делает `to_date` включительной.
        """
        return datetime.datetime.combine(
            self.to_date + datetime.timedelta(days=1),
            datetime.time.min,
            tzinfo=datetime.UTC,
        )


def resolve_period(
    from_date: datetime.date | None,
    to_date: datetime.date | None,
    *,
    today: datetime.date,
) -> StatsPeriod:
    """Разрешить период из опциональных `from`/`to` (ADR-0011 Решение 4).

    - `to` отсутствует → `today`; `from` отсутствует → `resolved_to − 30 дней`.
    - `from > to` → `PeriodError`.
    """
    resolved_to = to_date if to_date is not None else today
    resolved_from = (
        from_date
        if from_date is not None
        else resolved_to - datetime.timedelta(days=_DEFAULT_WINDOW_DAYS)
    )
    if resolved_from > resolved_to:
        raise PeriodError(f"from ({resolved_from.isoformat()}) > to ({resolved_to.isoformat()})")
    return StatsPeriod(from_date=resolved_from, to_date=resolved_to)
