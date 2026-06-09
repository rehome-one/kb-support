"""Доменный DTO клиента PaymentReleaseChecker (E10-7, #197).

Наша модель, независимая от провизорной формы (ADR-0014). Маппинг — в `adapter.py`.
Результат ИНФОРМАЦИОНЕН (ADR-0014 U4): case_state не блокирует, хранится в payload.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Clearance:
    """Вердикт возможности выплаты. `reason` — нейтральная строка (без ПДн)."""

    clearable: bool
    reason: str | None
