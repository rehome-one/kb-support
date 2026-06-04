"""Исполнители действий правил автоматизации (E5-4 #106; ADR-0008 Реш.3/4/5).

`apply_action` — best-effort изоляция (Реш.4): каждое действие в своём try; сбой
логируется (`error`, без ПДн) + метрика `automation_rule_failed`, НЕ пробрасывается
(не роняет заявку/прочие действия), без `except: pass`. Гранулярность «на действие» —
per-rule-обёртку добавит оркестратор #107.

Действия выполняются поверх существующих механизмов (правило трёх): assign/escalate/
set_status — через `TicketActionService`; set_priority/add_tag — через `record_changes`.
Аудит-актор — `AUTOMATION_ACTOR_ID` (системный, решение Архитектора #106), `automation_
rule_id` кладётся в `to_value` (трассируемость). notify/create_service_order — config-
gated seam'ы (Реш.3): лог намерения без ПДн, доставка/заказ — E7/#77.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.system_actors import AUTOMATION_ACTOR_ID
from api.automation.enums import AssignStrategy, AutomationActionType
from api.automation.metrics import record_action_deferred, record_rule_failure
from api.automation.schemas import (
    AddTagParams,
    AssignParams,
    CreateServiceOrderParams,
    EscalateParams,
    NotifyParams,
    SetPriorityParams,
    SetStatusParams,
)
from api.observability.logging import get_logger
from api.tickets.actions import TicketActionService
from api.tickets.enums import TicketStatus
from api.tickets.history import TicketHistoryRepository, record_changes
from api.tickets.models import Ticket

_logger = get_logger("automation.actions")

# Исполнитель: мутирует заявку + пишет аудит; кидает при доменной/валидационной ошибке
# (ловится `apply_action`). `rule_id` — для трассируемости в журнале/метриках.
Executor = Callable[[AsyncSession, Ticket, Mapping[str, Any], uuid.UUID], Awaitable[None]]


def _audit_extra(rule_id: uuid.UUID) -> dict[str, str]:
    return {"automation_rule_id": str(rule_id)}


async def _exec_assign(
    session: AsyncSession, ticket: Ticket, params: Mapping[str, Any], rule_id: uuid.UUID
) -> None:
    parsed = AssignParams.model_validate(params)
    if parsed.strategy != AssignStrategy.DIRECT:
        # round_robin/least_load: резолвер пула операторов — #109 (platform/#77).
        # Наблюдаемый недо-резолв (не тихий пропуск): warning + метрика.
        _logger.warning(
            "automation_assign_strategy_deferred rule_id=%s strategy=%s ticket_id=%s",
            rule_id,
            parsed.strategy.value,
            ticket.id,
        )
        record_action_deferred(
            action="assign", reason=f"strategy_{parsed.strategy.value}_unresolved"
        )
        return
    if parsed.operator_id is None:  # защитно — cross-field валидатор это гарантирует
        raise ValueError("assign.direct без operator_id")
    await TicketActionService(session).assign(
        ticket,
        AUTOMATION_ACTOR_ID,
        assignee_id=parsed.operator_id,
        team=parsed.team,
        extra=_audit_extra(rule_id),
    )


async def _exec_set_status(
    session: AsyncSession, ticket: Ticket, params: Mapping[str, Any], rule_id: uuid.UUID
) -> None:
    parsed = SetStatusParams.model_validate(params)
    await TicketActionService(session).transition(
        ticket, parsed.status, AUTOMATION_ACTOR_ID, extra=_audit_extra(rule_id)
    )


async def _exec_set_priority(
    session: AsyncSession, ticket: Ticket, params: Mapping[str, Any], rule_id: uuid.UUID
) -> None:
    parsed = SetPriorityParams.model_validate(params)
    before = {"priority": ticket.priority}
    ticket.priority = parsed.priority.value
    await session.flush()
    after = {"priority": ticket.priority}
    await record_changes(
        TicketHistoryRepository(session),
        ticket.id,
        AUTOMATION_ACTOR_ID,
        before,
        after,
        extra=_audit_extra(rule_id),
    )


async def _exec_add_tag(
    session: AsyncSession, ticket: Ticket, params: Mapping[str, Any], rule_id: uuid.UUID
) -> None:
    parsed = AddTagParams.model_validate(params)
    current = list(ticket.tags or [])
    merged = current + [tag for tag in parsed.tags if tag not in current]
    if merged == current:
        return  # дедуп: все теги уже есть → идемпотентно, без записи в журнал
    before = {"tags": current}
    ticket.tags = merged
    await session.flush()
    after = {"tags": list(ticket.tags)}
    await record_changes(
        TicketHistoryRepository(session),
        ticket.id,
        AUTOMATION_ACTOR_ID,
        before,
        after,
        extra=_audit_extra(rule_id),
    )


async def _exec_escalate(
    session: AsyncSession, ticket: Ticket, params: Mapping[str, Any], rule_id: uuid.UUID
) -> None:
    parsed = EscalateParams.model_validate(params)
    if parsed.team is not None:
        ticket.team = parsed.team.value
    await TicketActionService(session).transition(
        ticket,
        TicketStatus.ESCALATED,
        AUTOMATION_ACTOR_ID,
        extra={**_audit_extra(rule_id), "reason": "automation"},
    )


async def _exec_notify(
    session: AsyncSession, ticket: Ticket, params: Mapping[str, Any], rule_id: uuid.UUID
) -> None:
    # seam (ADR-0008 Реш.3): доставка уведомлений — E7. Лог намерения БЕЗ ПДн
    # (recipient/channel — конфиг, не тело сообщения; NFR-1.3).
    parsed = NotifyParams.model_validate(params)
    _logger.info(
        "automation_notify_intent rule_id=%s ticket_id=%s recipient=%s channel=%s",
        rule_id,
        ticket.id,
        parsed.recipient.value,
        parsed.channel or "-",
    )
    # TODO(E7): реальная доставка уведомления (email/push/чат, ADR-0005 Реш.4).


async def _exec_create_service_order(
    session: AsyncSession, ticket: Ticket, params: Mapping[str, Any], rule_id: uuid.UUID
) -> None:
    # seam (ADR-0008 Реш.3): боевой путь — platform/#77. Лог намерения БЕЗ ПДн.
    parsed = CreateServiceOrderParams.model_validate(params)
    _logger.info(
        "automation_service_order_intent rule_id=%s ticket_id=%s category=%s",
        rule_id,
        ticket.id,
        parsed.collaborator_category or "-",
    )
    # TODO(#77): реальный заказ коллаборанта (platform-вызов config-gated).


_DISPATCH: dict[str, Executor] = {
    AutomationActionType.ASSIGN.value: _exec_assign,
    AutomationActionType.SET_STATUS.value: _exec_set_status,
    AutomationActionType.SET_PRIORITY.value: _exec_set_priority,
    AutomationActionType.ADD_TAG.value: _exec_add_tag,
    AutomationActionType.ESCALATE.value: _exec_escalate,
    AutomationActionType.NOTIFY.value: _exec_notify,
    AutomationActionType.CREATE_SERVICE_ORDER.value: _exec_create_service_order,
}


async def apply_action(
    session: AsyncSession,
    ticket: Ticket,
    action: Mapping[str, Any],
    *,
    rule_id: uuid.UUID,
    trigger: str,
) -> bool:
    """Исполнить одно действие правила. Best-effort (ADR-0008 Реш.4): сбой логируется
    + метрика, НЕ пробрасывается. True — успех, False — сбой/неизвестное действие."""
    action_type = action.get("action")
    params = action.get("params") or {}
    executor = _DISPATCH.get(action_type) if isinstance(action_type, str) else None
    if executor is None:
        _logger.error(
            "automation_action_unknown rule_id=%s action=%s trigger=%s ticket_id=%s",
            rule_id,
            action_type,
            trigger,
            ticket.id,
        )
        record_rule_failure(rule_id=str(rule_id), action=str(action_type), trigger=trigger)
        return False
    try:
        await executor(session, ticket, params, rule_id)
        return True
    except Exception:
        # Best-effort изоляция: сбой ВИДЕН (error-лог без ПДн + метрика), но не роняет
        # заявку и прочие действия (ADR-0008 Реш.4, урок «no silent caps» #90).
        _logger.error(
            "automation_action_failed rule_id=%s action=%s trigger=%s ticket_id=%s",
            rule_id,
            action_type,
            trigger,
            ticket.id,
            exc_info=True,
        )
        record_rule_failure(rule_id=str(rule_id), action=str(action_type), trigger=trigger)
        return False
