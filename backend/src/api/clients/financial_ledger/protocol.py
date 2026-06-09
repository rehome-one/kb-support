"""Интерфейс клиента FinancialLedger (E10-7 PR-2, #197).

`record_entry` — мутация: при сбое (AT-003) бросает типизированную ошибку (паттерн
bank #197/kb-files #143); fire-after-вызывающий (decision_dispatch) ловит и логирует
(best-effort, durable — #79). Потребитель зависит от Protocol+DTO, не от провизорной формы.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.financial_ledger.models import LedgerEntry, LedgerResult


@runtime_checkable
class FinancialLedgerClient(Protocol):
    async def record_entry(self, entry: LedgerEntry) -> LedgerResult: ...
