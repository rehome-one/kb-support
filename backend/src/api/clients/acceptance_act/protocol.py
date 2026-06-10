"""Интерфейс клиента AcceptanceAct (E10-9 PR-A, #199).

`get_act` — чтение: при деградации (AT-003) возвращает `None` (мягкая, как
PaymentReleaseChecker #197). Потребитель (`tickets/acceptance`) зависит от Protocol+DTO,
не от HTTP-реализации/провизорной формы.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from api.clients.acceptance_act.models import AcceptanceAct


@runtime_checkable
class AcceptanceActClient(Protocol):
    async def get_act(self, acceptance_act_id: uuid.UUID) -> AcceptanceAct | None: ...
