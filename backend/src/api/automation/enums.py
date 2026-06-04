"""Доменные перечисления автоматизации (ТЗ §3.9, ADR-0008).

Значения строк — **дословно** из контракта `docs/openapi.yaml` (схема
`AutomationRule`: `trigger` и `actions[].action`). Контракт immutable — источник
правды домена (решение Архитектора, Issue #5).

Хранятся в БД как `String` + валидация Python-энумом на уровне приложения
(E1-конвенция, ADR-0007/0008 — без нативного PG ENUM, справочник настраиваем).
Эти классы — seed-набор по умолчанию и валидатор на границе API (#104).
"""

from __future__ import annotations

import enum


class AutomationTrigger(str, enum.Enum):
    """Когда срабатывает правило (ТЗ §3.9). on_create/on_update — синхронно в
    request-lifecycle; on_sla_breach/time_based — config-gated, до ops (ADR-0008 Реш.6)."""

    ON_CREATE = "on_create"
    ON_UPDATE = "on_update"
    ON_SLA_BREACH = "on_sla_breach"
    TIME_BASED = "time_based"


class AutomationActionType(str, enum.Enum):
    """Действие правила (ТЗ §3.9). notify/create_service_order — config-gated seam'ы
    (ADR-0008 Реш.3): доставка уведомлений — E7; заказ коллаборанта — platform/#77."""

    ASSIGN = "assign"
    SET_STATUS = "set_status"
    SET_PRIORITY = "set_priority"
    ADD_TAG = "add_tag"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    CREATE_SERVICE_ORDER = "create_service_order"
