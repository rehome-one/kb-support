"""Admin CRUD эндпоинты правил автоматизации (E5-2 #104, §6 ТЗ; ADR-0008).

`AutomationRule` настраивается администратором (скоуп `staff_admin`). Вся группа —
admin-only (чтение и запись): не-админ → 403 (как SLA #86). ПДн нет (конфигурация).
Доступ к чужим БД отсутствует — только своя таблица (арх-константа). conditions/actions
валидируются типизированно на границе, в БД — JSONB.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.automation.repository import AutomationRuleRepository
from api.automation.schemas import (
    AutomationRuleEnvelope,
    AutomationRuleInput,
    AutomationRuleListEnvelope,
    AutomationRuleRead,
    AutomationRuleUpdate,
)
from api.db import get_session
from api.errors import ProblemException

router = APIRouter(prefix="/api/v1/support", tags=["Automation"])


def _require_admin(principal: Principal) -> None:
    """RBAC: вся automation-конфигурация доступна только админу (`staff_admin`), иначе 403."""
    if not principal.is_staff_admin:
        raise ProblemException.forbidden(detail="Staff admin scope required")


def _resolve_request_id(raw: str | None) -> uuid.UUID:
    """Взять request_id из заголовка `X-Request-Id` или сгенерировать новый."""
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


def _create_values(payload: AutomationRuleInput) -> dict[str, Any]:
    """AutomationRuleInput → значения колонок (conditions/actions → JSON для JSONB;
    `order` → колонка `apply_order`)."""
    return {
        "name": payload.name,
        "trigger": payload.trigger.value,
        "conditions": payload.conditions.model_dump(mode="json", exclude_none=True),
        "actions": [
            action.model_dump(mode="json", exclude_none=True) for action in payload.actions
        ],
        "is_active": payload.is_active,
        "apply_order": payload.order,
    }


def _update_changes(payload: AutomationRuleUpdate) -> dict[str, Any]:
    """AutomationRuleUpdate → изменяемые колонки (только переданные поля)."""
    fields = payload.model_fields_set
    changes: dict[str, Any] = {}
    if "name" in fields:
        changes["name"] = payload.name
    if "trigger" in fields and payload.trigger is not None:
        changes["trigger"] = payload.trigger.value
    if "conditions" in fields and payload.conditions is not None:
        changes["conditions"] = payload.conditions.model_dump(mode="json", exclude_none=True)
    if "actions" in fields and payload.actions is not None:
        changes["actions"] = [a.model_dump(mode="json", exclude_none=True) for a in payload.actions]
    if "is_active" in fields:
        changes["is_active"] = payload.is_active
    if "order" in fields and payload.order is not None:
        changes["apply_order"] = payload.order
    return changes


@router.get(
    "/automation-rules",
    response_model=AutomationRuleListEnvelope,
    summary="Список правил автоматизации",
)
async def list_automation_rules(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> AutomationRuleListEnvelope:
    _require_admin(principal)
    items = await AutomationRuleRepository(session).list_all()
    return AutomationRuleListEnvelope(
        data=[AutomationRuleRead.model_validate(item) for item in items],
        request_id=_resolve_request_id(x_request_id),
    )


@router.post(
    "/automation-rules",
    status_code=status.HTTP_201_CREATED,
    response_model=AutomationRuleEnvelope,
    summary="Создать правило автоматизации",
)
async def create_automation_rule(
    payload: AutomationRuleInput,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> AutomationRuleEnvelope:
    _require_admin(principal)
    rule = await AutomationRuleRepository(session).create(_create_values(payload))
    await session.commit()
    await session.refresh(rule)
    return AutomationRuleEnvelope(
        data=AutomationRuleRead.model_validate(rule),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/automation-rules/{rule_id}",
    response_model=AutomationRuleEnvelope,
    summary="Правило автоматизации",
)
async def get_automation_rule(
    rule_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> AutomationRuleEnvelope:
    _require_admin(principal)
    rule = await AutomationRuleRepository(session).get(rule_id)
    if rule is None:
        raise ProblemException.not_found(detail="Automation rule not found")
    return AutomationRuleEnvelope(
        data=AutomationRuleRead.model_validate(rule),
        request_id=_resolve_request_id(x_request_id),
    )


@router.patch(
    "/automation-rules/{rule_id}",
    response_model=AutomationRuleEnvelope,
    summary="Изменить правило автоматизации",
)
async def update_automation_rule(
    rule_id: uuid.UUID,
    payload: AutomationRuleUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> AutomationRuleEnvelope:
    _require_admin(principal)
    repository = AutomationRuleRepository(session)
    rule = await repository.get(rule_id)
    if rule is None:
        raise ProblemException.not_found(detail="Automation rule not found")
    rule = await repository.update(rule, _update_changes(payload))
    await session.commit()
    await session.refresh(rule)
    return AutomationRuleEnvelope(
        data=AutomationRuleRead.model_validate(rule),
        request_id=_resolve_request_id(x_request_id),
    )
