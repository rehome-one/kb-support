"""Доменный DTO клиента AcceptanceAct (E10-9 PR-A, #199).

Наша модель, независимая от провизорной формы (ADR-0016). Маппинг — в `adapter.py`.
`damage_amount` — сумма ущерба КАК ССЫЛКА из акта (kb-support деньги не считает, FR-9.8);
триггер каскада MOVE_OUT→COMPENSATION (D3). `kind`/`signing_status` — строки домена
ActKind/SigningStatus (валидация на потреблении).
"""

from __future__ import annotations

import decimal
from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptanceAct:
    """Состояние акта приёмки-передачи из upstream (провизорно, ADR-0016/0014)."""

    id: str
    kind: str
    signing_status: str
    damage_amount: decimal.Decimal | None
