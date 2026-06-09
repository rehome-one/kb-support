"""Доменные DTO клиента BankProvider (E10-7, #197).

Наши модели, независимые от провизорной формы BankProvider API (ADR-0014). Маппинг
провизорный JSON → DTO живёт в `adapter.py` (стиль ADR-0006/0010). Деньги НЕ считаем
(FR-9.8) — `amount` лишь передаётся как утверждённая сумма выплаты.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PayoutRequest:
    """Запрос выплаты по решению претензии. `reference` — человекочитаемая ссылка
    (номер заявки) для сверки на стороне банка; суммы точные (Decimal)."""

    ticket_id: uuid.UUID
    amount: Decimal
    currency: str
    reference: str


@dataclass(frozen=True)
class PayoutResult:
    """Подтверждение приёма выплаты банком. `payment_id` → `Ticket.linked_payment_id`
    (запись — через webhook `payout_released` E10-8 / durable #79)."""

    payment_id: str
