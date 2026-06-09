"""Расчёт состояния SLA на чтении (E4-5 #89, FR-4.3) — без воркера.

Чистые функции (`now` инъектируется). `sla_state` = худшее из двух «ног» — первого
ответа и решения. **Решение Архитектора (#89): `approaching` = осталось <20% окна**
(`deadline − created_at`).

Учёт текущей паузы (снятие seam #88): для незавершённой ноги решения «время сейчас»
заморожено на `sla_paused_at`, пока заявка на паузе (PENDING/WAITING) — поэтому
пауза не приводит к ложному breach. Норматив первого ответа паузами не двигается.

Модель «as_of»: для завершённой ноги (ответили/решили) сравниваем факт-метку с
дедлайном (уложились → ok, позже → breached); для незавершённой — now (или
`sla_paused_at` для замороженной паузой ноги решения).
"""

from __future__ import annotations

import datetime
from typing import Literal

from api.tickets.enums import TicketCaseState

SlaStateValue = Literal["none", "ok", "approaching", "breached"]

# Доля окна (deadline − created_at), при остатке меньше которой состояние = approaching.
_APPROACHING_FRACTION = 0.2
_SEVERITY = {"ok": 0, "approaching": 1, "breached": 2}


def _leg_state(
    created_at: datetime.datetime,
    deadline: datetime.datetime,
    as_of: datetime.datetime,
    *,
    settled: bool,
) -> SlaStateValue:
    """Состояние одной ноги SLA по «as_of»-времени.

    `settled` — нога завершена (ответ дан / заявка решена): approaching неприменим
    (либо уложились → ok, либо просрочено → breached)."""
    if as_of >= deadline:
        return "breached"
    if settled:
        return "ok"
    window = (deadline - created_at).total_seconds()
    remaining = (deadline - as_of).total_seconds()
    if window > 0 and remaining < _APPROACHING_FRACTION * window:
        return "approaching"
    return "ok"


def compute_sla_state(
    now: datetime.datetime,
    *,
    created_at: datetime.datetime,
    first_response_due_at: datetime.datetime | None,
    first_responded_at: datetime.datetime | None,
    resolution_due_at: datetime.datetime | None,
    resolved_at: datetime.datetime | None,
    sla_paused_at: datetime.datetime | None,
) -> SlaStateValue:
    """Состояние SLA = худшее из активных ног (первый ответ + решение).

    Нет ни одного дедлайна (заявка без SLA) → `none`.
    """
    legs: list[SlaStateValue] = []

    if first_response_due_at is not None:
        # Первый ответ паузами НЕ двигается (#88).
        if first_responded_at is not None:
            legs.append(
                _leg_state(created_at, first_response_due_at, first_responded_at, settled=True)
            )
        else:
            legs.append(_leg_state(created_at, first_response_due_at, now, settled=False))

    if resolution_due_at is not None:
        if resolved_at is not None:
            legs.append(_leg_state(created_at, resolution_due_at, resolved_at, settled=True))
        else:
            # Незавершённая нога: при текущей паузе «сейчас» заморожено на начале паузы.
            as_of = sla_paused_at if sla_paused_at is not None else now
            legs.append(_leg_state(created_at, resolution_due_at, as_of, settled=False))

    if not legs:
        return "none"
    return max(legs, key=lambda state: _SEVERITY[state])


def is_resolution_breached(
    now: datetime.datetime,
    *,
    resolution_due_at: datetime.datetime | None,
    resolved_at: datetime.datetime | None,
    sla_paused_at: datetime.datetime | None,
) -> bool:
    """Нарушен ли дедлайн РЕШЕНИЯ (для `sla_breached`), с учётом паузы и факта решения.

    as_of = resolved_at (уложились?) ИЛИ sla_paused_at (заморожено паузой) ИЛИ now.
    Согласовано с SQL-фильтром `?sla_breached` (COALESCE(resolved_at, sla_paused_at, now))."""
    if resolution_due_at is None:
        return False
    as_of = resolved_at if resolved_at is not None else (sla_paused_at or now)
    return as_of >= resolution_due_at


def is_first_response_breached(
    now: datetime.datetime,
    *,
    first_response_due_at: datetime.datetime | None,
    first_responded_at: datetime.datetime | None,
) -> bool:
    """Нарушен ли дедлайн ПЕРВОГО ОТВЕТА.

    Первый ответ паузами НЕ двигается (#88): нога «открыта», пока нет
    `first_responded_at`. Зеркало SQL `first_response_breached_clause`."""
    if first_response_due_at is None or first_responded_at is not None:
        return False
    return now >= first_response_due_at


def is_payout_breached(
    now: datetime.datetime,
    *,
    case_state: str | None,
    payout_due_at: datetime.datetime | None,
) -> bool:
    """Нарушен ли дедлайн ВЫПЛАТЫ (claims, E10-6 #196). Зеркало `payout_breached_clause`.

    Актуально только пока заявка в PAYOUT_PENDING (после PAID срок не «висит»)."""
    if payout_due_at is None or case_state != TicketCaseState.PAYOUT_PENDING.value:
        return False
    return now >= payout_due_at
