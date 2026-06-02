"""Pydantic-схемы admin CRUD для SLA-конфигурации (E4-2 #86, §6 ТЗ).

Контракт — `docs/openapi.yaml` (схемы `SLAPolicy`/`SLAPolicyInput`/`BusinessHours`/
`BusinessHoursInput`). ПДн здесь нет — это конфигурация (политики и графики).

**Форма `business_hours.schedule`** (решение Архитектора, #86): объект «день →
массив интервалов», где интервал — пара `["HH:MM", "HH:MM"]` (24-часовой формат,
`open < close`). Отсутствующий день или пустой массив = выходной. Интервалы в
пределах одних суток (пересечение полуночи не выражается; круглосуточно =
`business_hours_id=null` у политики). На эту форму опирается калькулятор #87.
"""

from __future__ import annotations

import datetime
import re
import uuid
import zoneinfo
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.tickets.enums import TicketPriority, TicketType

# Канонический порядок дней недели (ключи `schedule`).
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_SET = frozenset(WEEKDAYS)
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_timezone(value: str) -> str:
    """Проверить, что строка — валидная IANA-таймзона; иначе ValueError (→ 422)."""
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"неизвестная IANA-таймзона: {value!r}") from exc
    return value


def _parse_hhmm(value: str) -> datetime.time:
    """Распарсить `"HH:MM"` (24ч) в `time`; иначе — ValueError (→ 422)."""
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ValueError(f"время должно быть в формате HH:MM (24ч), получено: {value!r}")
    return datetime.time.fromisoformat(value)


def _validate_schedule(schedule: dict[str, Any]) -> dict[str, list[list[str]]]:
    """Проверить форму недельного графика; вернуть нормализованный dict.

    Правила: ключи ⊆ дней недели; значение — массив интервалов `[open, close]`;
    `open < close`; интервалы внутри дня не пересекаются. Пустой/отсутствующий
    день = выходной.
    """
    if not isinstance(schedule, dict):
        raise ValueError("schedule должен быть объектом «день → интервалы»")
    unknown = set(schedule) - _WEEKDAY_SET
    if unknown:
        raise ValueError(f"недопустимые дни в schedule: {sorted(unknown)}; допустимы {WEEKDAYS}")

    normalized: dict[str, list[list[str]]] = {}
    for day, intervals in schedule.items():
        if not isinstance(intervals, list):
            raise ValueError(f"{day}: интервалы должны быть массивом")
        parsed: list[tuple[datetime.time, datetime.time]] = []
        for interval in intervals:
            if not isinstance(interval, list | tuple) or len(interval) != 2:
                raise ValueError(
                    f"{day}: интервал должен быть парой [open, close], получено {interval!r}"
                )
            open_t, close_t = _parse_hhmm(interval[0]), _parse_hhmm(interval[1])
            if open_t >= close_t:
                raise ValueError(f"{day}: open должен быть строго раньше close ({interval!r})")
            parsed.append((open_t, close_t))
        parsed.sort()
        for (_, prev_close), (next_open, _) in zip(parsed, parsed[1:], strict=False):
            if next_open < prev_close:
                raise ValueError(f"{day}: интервалы пересекаются")
        normalized[day] = [[o.strftime("%H:%M"), c.strftime("%H:%M")] for o, c in parsed]
    return normalized


class AppliesTo(BaseModel):
    """Условия применения SLA-политики (контракт `SLAPolicy.applies_to`).

    `types`/`priorities` валидируются доменными энумами (неизвестное → 422).
    `requester_roles` — свободный список строк (домен ролей заявителя ещё не
    зафиксирован на бэке; матчер #87 сравнивает строки)."""

    model_config = ConfigDict(extra="forbid")

    types: list[TicketType] | None = None
    priorities: list[TicketPriority] | None = None
    requester_roles: list[str] | None = None


# --- BusinessHours ---


class BusinessHoursInput(BaseModel):
    """Тело POST /business-hours (контракт `BusinessHoursInput`). Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=64)
    schedule: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, value: str) -> str:
        return _validate_timezone(value)

    @field_validator("schedule")
    @classmethod
    def _check_schedule(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_schedule(value)


class BusinessHoursUpdate(BaseModel):
    """Тело PATCH /business-hours/{id} — частичное обновление. Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    schedule: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, value: str | None) -> str | None:
        return None if value is None else _validate_timezone(value)

    @field_validator("schedule")
    @classmethod
    def _check_schedule(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else _validate_schedule(value)


class BusinessHoursRead(BaseModel):
    """Представление графика в ответе (контракт `BusinessHours`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    timezone: str
    schedule: dict[str, Any]
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class BusinessHoursEnvelope(BaseModel):
    """Конверт ответа с одним графиком (`ResponseEnvelope`)."""

    data: BusinessHoursRead
    request_id: uuid.UUID


class BusinessHoursListEnvelope(BaseModel):
    """Конверт ответа со списком графиков."""

    data: list[BusinessHoursRead]
    request_id: uuid.UUID


# --- SLAPolicy ---


class SLAPolicyInput(BaseModel):
    """Тело POST /sla-policies (контракт `SLAPolicyInput`). Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    applies_to: AppliesTo = Field(default_factory=AppliesTo)
    first_response_minutes: int = Field(gt=0)
    resolution_minutes: int = Field(gt=0)
    business_hours_id: uuid.UUID | None = None
    priority: int = Field(default=0, ge=0)


class SLAPolicyUpdate(BaseModel):
    """Тело PATCH /sla-policies/{id} — частичное обновление. Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    applies_to: AppliesTo | None = None
    first_response_minutes: int | None = Field(default=None, gt=0)
    resolution_minutes: int | None = Field(default=None, gt=0)
    business_hours_id: uuid.UUID | None = None
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class SLAPolicyRead(BaseModel):
    """Представление SLA-политики в ответе (контракт `SLAPolicy`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # Хранится как канонический JSON (вход валидируется `AppliesTo`, сохраняется
    # с exclude_none). Отдаём ровно сохранённый dict — без null-ключей, чтобы
    # массивы types/priorities/requester_roles конформили контракту.
    applies_to: dict[str, Any]
    first_response_minutes: int
    resolution_minutes: int
    business_hours_id: uuid.UUID | None
    priority: int
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SLAPolicyEnvelope(BaseModel):
    """Конверт ответа с одной политикой (`ResponseEnvelope`)."""

    data: SLAPolicyRead
    request_id: uuid.UUID


class SLAPolicyListEnvelope(BaseModel):
    """Конверт ответа со списком политик."""

    data: list[SLAPolicyRead]
    request_id: uuid.UUID
