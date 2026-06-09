"""DTO доставки решения в ЛК заявителя (E10-7 PR-2, #197).

Наша модель, независимая от провизорной формы платформы (ADR-0014/0006). Доставка —
уведомление заявителя о принятом решении (FR-9.3, ADR-0013 D7 seam). ПДн (reason) — на
сервере; в логи доставки НЕ пишем (ФЗ-152).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DecisionNotification:
    """Уведомление о решении для ЛК. `requester_id` — адресат на платформе rehome.one."""

    ticket_id: uuid.UUID
    requester_id: uuid.UUID
    decision: str
    approved_amount: Decimal | None
    reason: str | None
