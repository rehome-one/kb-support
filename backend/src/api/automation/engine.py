"""Оркестрация движка автоматизации (E5-5 #107; ADR-0008 Реш.4/6).

`run_rules` связывает воедино: загрузка активных правил триггера (#103) → матчинг
условий (#105) → исполнение действий (#106). Синхронно в request-lifecycle (Реш.6:
on_create/on_update). Вызывается из `tickets.repository` (врезка) в ТОЙ ЖЕ транзакции,
commit — на стороне роутера → автоматизация атомарна с операцией заявки.

**Best-effort (Реш.4): `run_rules` НИКОГДА не пробрасывает** — сбой загрузки/матчинга/
действия/savepoint-механики логируется (без ПДн) + метрика, не роняет создание/обновление
заявки и прочие действия.

**SAVEPOINT-изоляция на действие.** Действия пишут в БД (flush); DB-уровневая ошибка
аборти́т ВСЮ Postgres-транзакцию (а с ней — commit заявки в роутере). Поэтому каждое
действие оборачивается в `begin_nested()` (SAVEPOINT): сбой откатывается до savepoint
(`ROLLBACK TO SAVEPOINT` восстанавливает соединение), частичная мутация снимается,
заявка и прочие действия целы. После отката — `session.refresh(ticket)` снимает «грязные»
in-memory атрибуты сбойного действия.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from api.automation.actions import apply_action
from api.automation.matcher import select_matching_rules
from api.automation.metrics import record_rule_failure
from api.automation.repository import AutomationRuleRepository
from api.observability.logging import get_logger
from api.tickets.models import Ticket

_logger = get_logger("automation.engine")


async def run_rules(session: AsyncSession, ticket: Ticket, trigger: str) -> None:
    """Прогнать правила триггера по заявке (best-effort, не пробрасывает)."""
    try:
        rules = await AutomationRuleRepository(session).list_active(trigger)
        if not rules:
            return
        ticket_text = f"{ticket.subject}\n{ticket.description}"
        matched = select_matching_rules(
            rules,
            ticket_type=ticket.type,
            ticket_priority=ticket.priority,
            ticket_channel=ticket.channel,
            ticket_status=ticket.status,
            ticket_text=ticket_text,
        )
    except Exception:
        # Сбой загрузки/матчинга не роняет заявку (Реш.4); ПДн не логируем.
        _logger.error(
            "automation_orchestration_failed trigger=%s ticket_id=%s",
            trigger,
            ticket.id,
            exc_info=True,
        )
        return
    for rule in matched:
        await run_actions(session, ticket, rule.actions, rule_id=rule.id, trigger=trigger)


async def run_actions(
    session: AsyncSession,
    ticket: Ticket,
    actions: Iterable[Mapping[str, Any]],
    *,
    rule_id: uuid.UUID,
    trigger: str,
) -> None:
    """Исполнить действия ОДНОГО правила, каждое в SAVEPOINT-изоляции (best-effort).

    Извлечено из `run_rules` для переиспользования сканом time_based (#110) без импорта
    приватного `_run_action_isolated`. Вызывается per-rule (сохраняет `rule_id` в
    метриках/логах). Не пробрасывает (ADR-0008 Реш.4)."""
    for action in actions:
        await _run_action_isolated(session, ticket, action, rule_id=rule_id, trigger=trigger)


async def _run_action_isolated(
    session: AsyncSession,
    ticket: Ticket,
    action: Mapping[str, Any],
    *,
    rule_id: uuid.UUID,
    trigger: str,
) -> None:
    """Одно действие в SAVEPOINT-изоляции. Любой сбой savepoint-механики или действия —
    best-effort (лог + метрика), НЕ пробрасывается (ADR-0008 Реш.4)."""
    action_type = str(action.get("action"))
    try:
        savepoint = await session.begin_nested()
    except Exception:
        _logger.error(
            "automation_savepoint_begin_failed rule_id=%s action=%s trigger=%s ticket_id=%s",
            rule_id,
            action_type,
            trigger,
            ticket.id,
            exc_info=True,
        )
        record_rule_failure(rule_id=str(rule_id), action=action_type, trigger=trigger)
        return

    ok = False
    try:
        ok = await apply_action(session, ticket, action, rule_id=rule_id, trigger=trigger)
    except Exception:  # apply_action ловит сам — защита от непредвиденного (Реш.4)
        ok = False

    try:
        if ok:
            await savepoint.commit()
        else:
            await savepoint.rollback()
            # Восстановить in-memory состояние заявки после отката сбойного действия
            # (#107 условие 2). `refresh` (async) перезагружает атрибуты СРАЗУ — в отличие
            # от `expire`, ленивая дозагрузка которого в async-контексте упала бы
            # MissingGreenlet при последующем sync-доступе (сериализация в роутере).
            # Прежние успешные действия этого прохода сохраняются (видны в текущей tx).
            await session.refresh(ticket)
    except Exception:
        _logger.error(
            "automation_savepoint_finalize_failed rule_id=%s action=%s trigger=%s ticket_id=%s",
            rule_id,
            action_type,
            trigger,
            ticket.id,
            exc_info=True,
        )
        record_rule_failure(rule_id=str(rule_id), action=action_type, trigger=trigger)
        await _recover_savepoint(session, savepoint, ticket)


async def _recover_savepoint(
    session: AsyncSession, savepoint: AsyncSessionTransaction, ticket: Ticket
) -> None:
    """Последняя попытка вернуть сессию в рабочее состояние после сбоя финализации."""
    try:
        await savepoint.rollback()
        await session.refresh(ticket)
    except Exception:
        _logger.error("automation_savepoint_recovery_failed ticket_id=%s", ticket.id, exc_info=True)
