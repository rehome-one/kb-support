"""Интерфейс клиента BankProvider (E10-7, #197).

Потребитель (fire-after выплаты в `tickets/payout_dispatch`) зависит от Protocol+DTO,
не от HTTP-реализации/провизорной формы. `release_payout` — мутация: при сбое (AT-003)
бросает типизированную ошибку (`ExternalServiceError`/`CircuitOpenError`) — у выплаты
нет «мягкой» деградации (паттерн kb-files #143, ADR-0010 Реш.4). Решение о судьбе —
у вызывающего (fire-after best-effort: лог, не роняет процесс; durable — #79).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.bank.models import PayoutRequest, PayoutResult


@runtime_checkable
class BankProviderClient(Protocol):
    async def release_payout(self, request: PayoutRequest) -> PayoutResult: ...
