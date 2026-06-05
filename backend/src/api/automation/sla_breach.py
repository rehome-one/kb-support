"""Мост SLA-воркер → движок автоматизации (E5 #108; FR-4.4, §3.9).

Подменяет дефолтный seam-хук `on_sla_breach` (#90) реальной эскалацией: на breach-
событие загружает заявку и прогоняет правила trigger=`on_sla_breach` (escalate/
set_priority/notify… — #106) через оркестратор #107. Замыкает связку SLA→эскалация.

**Инертен до ops (ADR-0008 Реш.6):** actor скана config-gated по пустому
`sla_worker_broker_url` (StubBroker → `check_sla_due` не enqueue'ится). Боевой путь —
с ops-воркером (#79). Read-side breach (#89) от этого не зависит.

**KNOWN-LIMITATION — повторная эскалация (решение Архитектора, Вариант 1; ADR-0007
Реш.4).** Дедуп-маркера «уже эскалирована» нет (seam `already_handled` в `scan.py` —
дефолтный `_never_handled`). Пока заявка просрочена, КАЖДЫЙ проход скана повторно
применяет on_sla_breach-правила: `escalate` не меняет статус на no-op (ESCALATED→
ESCALATED), НО пишет строку TicketHistory каждый проход (аудит-шум), а
`set_priority`/`notify` повторяют действие каждый цикл. До ops-воркера спама нет
(actor инертен). Дедуп-маркер — follow-up #120.

Сигнатуру seam'а #90 (`BreachHook`, event-only) НЕ меняем: сессию скана прокидываем
замыканием (фабрика). Заявка уже в identity-map скана → `session.get` без лишнего SELECT.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.automation.engine import run_rules
from api.automation.enums import AutomationTrigger
from api.observability.logging import get_logger
from api.sla.worker.hooks import BreachHook, SlaBreachEvent, on_sla_breach
from api.tickets.models import Ticket

_logger = get_logger("automation.sla_breach")


def make_sla_breach_hook(session: AsyncSession) -> BreachHook:
    """BreachHook, прогоняющий on_sla_breach-правила движка для заявки события.

    Best-effort: `run_rules` не пробрасывает (#107); исчезнувшая заявка → warning,
    не сбой. Замыкает `session` скана (та же транзакция → эскалация атомарна с проходом,
    commit — на стороне actor'а)."""

    async def _hook(event: SlaBreachEvent) -> None:
        await on_sla_breach(event)  # структурный лог breach (наблюдаемость, без ПДн)
        ticket = await session.get(Ticket, event.ticket_id)
        if ticket is None:
            _logger.warning("sla_breach_ticket_gone ticket_id=%s", event.ticket_id)
            return
        await run_rules(session, ticket, AutomationTrigger.ON_SLA_BREACH.value)

    return _hook
