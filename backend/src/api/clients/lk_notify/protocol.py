"""Интерфейс доставки решения в ЛК (E10-7 PR-2, #197).

`notify_decision` — мутация (уведомление): при сбое (AT-003) бросает типизированную
ошибку; fire-after-вызывающий (decision_dispatch) ловит и логирует (best-effort,
durable — #79). Потребитель зависит от Protocol+DTO, не от провизорной формы.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.lk_notify.models import DecisionNotification


@runtime_checkable
class LkNotifyClient(Protocol):
    async def notify_decision(self, notification: DecisionNotification) -> None: ...
