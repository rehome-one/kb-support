"""breach-хук SLA-воркера (E4-6, #90) — seam под эскалацию (FR-4.4).

`SlaBreachEvent` несёт ТОЛЬКО не-ПДн поля (NFR-1.3 / ФЗ-152): id/номер/тип/
приоритет/команда + флаги нарушенных ног. Контекст ноги (первый ответ vs решение)
фиксируется здесь, чтобы сигнатуру хука не пришлось менять в E5.

Дефолтный `on_sla_breach` — только структурный лог. Реальные действия эскалации
(смена приоритета/команды, уведомление) — E5/#18 через AutomationRule.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Awaitable, Callable

from api.observability.logging import get_logger

_logger = get_logger("sla.worker")


@dataclasses.dataclass(frozen=True)
class SlaBreachEvent:
    """Контекст нарушения SLA для хука. Без ПДн — только доменные метки заявки."""

    ticket_id: uuid.UUID
    number: str
    type: str
    priority: str
    team: str | None
    first_response_breached: bool
    resolution_breached: bool


# Сигнатура seam'а эскалации. E5/#18 подменяет дефолт реальным действием.
BreachHook = Callable[[SlaBreachEvent], Awaitable[None]]


def _legs(event: SlaBreachEvent) -> str:
    legs = []
    if event.first_response_breached:
        legs.append("first_response")
    if event.resolution_breached:
        legs.append("resolution")
    return ",".join(legs) or "-"


async def on_sla_breach(event: SlaBreachEvent) -> None:
    """Дефолтный хук: структурный лог без ПДн.

    # TODO(E5/#18): реальная эскалация через AutomationRule (приоритет/команда/
    # уведомление). В E4 это только seam — действий нет.
    """
    _logger.warning(
        "sla_breach ticket_id=%s number=%s type=%s priority=%s team=%s legs=%s",
        event.ticket_id,
        event.number,
        event.type,
        event.priority,
        event.team or "-",
        _legs(event),
    )
