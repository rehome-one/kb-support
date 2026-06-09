"""breach-хук SLA-воркера (E4-6, #90) — seam под эскалацию (FR-4.4).

`SlaBreachEvent` несёт ТОЛЬКО не-ПДн поля (NFR-1.3 / ФЗ-152): id/номер/тип/
приоритет/команда + флаги нарушенных ног. Контекст ноги (первый ответ vs решение)
фиксируется здесь, чтобы сигнатуру хука не пришлось менять в E5.

Дефолтный `on_sla_breach` — только структурный лог. Реальные действия эскалации
(смена приоритета/команды, уведомление) — через AutomationRule (#108,
`api.automation.sla_breach`), которым actor подменяет дефолт.
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
    # Дедлайн выплаты претензии (claims, E10-6 #196). Default — backward-compatible
    # для существующих конструкторов/тестов E4.
    payout_breached: bool = False


# Сигнатура seam'а эскалации. E5/#18 подменяет дефолт реальным действием.
BreachHook = Callable[[SlaBreachEvent], Awaitable[None]]


def _legs(event: SlaBreachEvent) -> str:
    legs = []
    if event.first_response_breached:
        legs.append("first_response")
    if event.resolution_breached:
        legs.append("resolution")
    if event.payout_breached:
        legs.append("payout")
    return ",".join(legs) or "-"


async def on_sla_breach(event: SlaBreachEvent) -> None:
    """Дефолтный хук: структурный лог breach без ПДн (seam для инертного/тестового пути).

    Боевая эскалация через AutomationRule (trigger=on_sla_breach) — выполнена в #108
    (`api.automation.sla_breach.make_sla_breach_hook`), которым actor подменяет этот
    дефолт. Здесь остаётся только структурный лог: его переиспользует и боевой мост
    (наблюдаемость breach сохраняется).
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
