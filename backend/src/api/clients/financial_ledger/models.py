"""Доменные DTO клиента FinancialLedger (E10-7 PR-2, #197).

Наши модели, независимые от провизорной формы (ADR-0014). kb-support деньги НЕ считает
(FR-9.8) — лишь фиксирует РЕШЕНИЕ как ссылку-проводку (сумма уже утверждена в decide).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LedgerEntry:
    """Проводка-ссылка решения по претензии. `amount` = approved_amount (None у REJECTED)."""

    ticket_id: uuid.UUID
    decision: str
    amount: Decimal | None
    reference: str


@dataclass(frozen=True)
class LedgerResult:
    """Подтверждение записи проводки. `entry_id` — id проводки в ledger (логируется)."""

    entry_id: str
