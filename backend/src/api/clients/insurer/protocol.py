"""Интерфейс клиента страховщика (E10-10 PR-B #200).

`send_event` — мутация (передача события): при сбое (AT-003) бросает типизированную ошибку
(`ExternalServiceError`/`CircuitOpenError`) — у передачи нет «мягкой» деградации (как
BankProvider #143, ADR-0010 Реш.4). Судьбу решает вызывающий (fire-after best-effort: лог,
не роняет процесс; durable — #79).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.insurer.models import InsurerEvent


@runtime_checkable
class InsurerClient(Protocol):
    async def send_event(self, event: InsurerEvent) -> None: ...
