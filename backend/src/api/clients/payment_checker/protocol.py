"""Интерфейс клиента PaymentReleaseChecker (E10-7, #197).

`check_clearance` — чтение: при деградации (AT-003) возвращает `None` (мягкая
деградация, как platform #71/kb-wiki #129) — проверка ИНФОРМАЦИОННА и не блокирует
case_state (ADR-0014 U4). Потребитель (`tickets/payout_dispatch`) зависит от
Protocol+DTO, не от HTTP-реализации/провизорной формы.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from api.clients.payment_checker.models import Clearance


@runtime_checkable
class PaymentReleaseCheckerClient(Protocol):
    async def check_clearance(self, ticket_id: uuid.UUID) -> Clearance | None: ...
