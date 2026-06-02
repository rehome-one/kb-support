"""Admin CRUD эндпоинты SLA-конфигурации (E4-2 #86, §6 ТЗ).

`SLAPolicy` и `BusinessHours` настраиваются администратором (скоуп `staff_admin`).
Вся группа — admin-only (чтение и запись): не-админ → 403 (решение Архитектора
#86). ПДн нет (конфигурация). Доступ к чужим БД отсутствует — только свои таблицы
(арх-константа).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.db import get_session
from api.errors import ProblemException
from api.sla.repository import BusinessHoursRepository, SLAPolicyRepository
from api.sla.schemas import (
    BusinessHoursEnvelope,
    BusinessHoursInput,
    BusinessHoursListEnvelope,
    BusinessHoursRead,
    BusinessHoursUpdate,
    SLAPolicyEnvelope,
    SLAPolicyInput,
    SLAPolicyListEnvelope,
    SLAPolicyRead,
    SLAPolicyUpdate,
)

router = APIRouter(prefix="/api/v1/support", tags=["SLA"])


def _require_admin(principal: Principal) -> None:
    """RBAC: вся SLA-конфигурация доступна только админу (`staff_admin`), иначе 403."""
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


async def _ensure_business_hours_exists(
    session: AsyncSession, business_hours_id: uuid.UUID | None
) -> None:
    """Детерминированно проверить существование графика (→ 422, не 500 от FK)."""
    if business_hours_id is None:
        return
    if await BusinessHoursRepository(session).get(business_hours_id) is None:
        raise ProblemException.unprocessable(
            detail="business_hours_id does not reference an existing business hours record"
        )


def _policy_create_values(payload: SLAPolicyInput) -> dict[str, Any]:
    """SLAPolicyInput → значения колонок (applies_to сериализуется в JSON для JSONB)."""
    return {
        "name": payload.name,
        "applies_to": payload.applies_to.model_dump(mode="json", exclude_none=True),
        "first_response_minutes": payload.first_response_minutes,
        "resolution_minutes": payload.resolution_minutes,
        "business_hours_id": payload.business_hours_id,
        "priority": payload.priority,
    }


def _policy_update_changes(payload: SLAPolicyUpdate) -> dict[str, Any]:
    """SLAPolicyUpdate → изменяемые колонки (только переданные поля; uuid не json-ится)."""
    fields = payload.model_fields_set
    changes: dict[str, Any] = {}
    if "name" in fields:
        changes["name"] = payload.name
    if "applies_to" in fields and payload.applies_to is not None:
        changes["applies_to"] = payload.applies_to.model_dump(mode="json", exclude_none=True)
    if "first_response_minutes" in fields:
        changes["first_response_minutes"] = payload.first_response_minutes
    if "resolution_minutes" in fields:
        changes["resolution_minutes"] = payload.resolution_minutes
    if "business_hours_id" in fields:
        # Допускается явное зануление (24/7).
        changes["business_hours_id"] = payload.business_hours_id
    if "priority" in fields:
        changes["priority"] = payload.priority
    if "is_active" in fields:
        changes["is_active"] = payload.is_active
    return changes


# --- BusinessHours ---


@router.get(
    "/business-hours",
    response_model=BusinessHoursListEnvelope,
    summary="Список графиков рабочего времени",
)
async def list_business_hours(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> BusinessHoursListEnvelope:
    _require_admin(principal)
    items = await BusinessHoursRepository(session).list_all()
    return BusinessHoursListEnvelope(
        data=[BusinessHoursRead.model_validate(item) for item in items],
        request_id=_resolve_request_id(x_request_id),
    )


@router.post(
    "/business-hours",
    status_code=status.HTTP_201_CREATED,
    response_model=BusinessHoursEnvelope,
    summary="Создать график рабочего времени",
)
async def create_business_hours(
    payload: BusinessHoursInput,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> BusinessHoursEnvelope:
    _require_admin(principal)
    business_hours = await BusinessHoursRepository(session).create(
        {"name": payload.name, "timezone": payload.timezone, "schedule": payload.schedule}
    )
    await session.commit()
    await session.refresh(business_hours)
    return BusinessHoursEnvelope(
        data=BusinessHoursRead.model_validate(business_hours),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/business-hours/{business_hours_id}",
    response_model=BusinessHoursEnvelope,
    summary="График рабочего времени",
)
async def get_business_hours(
    business_hours_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> BusinessHoursEnvelope:
    _require_admin(principal)
    business_hours = await BusinessHoursRepository(session).get(business_hours_id)
    if business_hours is None:
        raise ProblemException.not_found(detail="Business hours not found")
    return BusinessHoursEnvelope(
        data=BusinessHoursRead.model_validate(business_hours),
        request_id=_resolve_request_id(x_request_id),
    )


@router.patch(
    "/business-hours/{business_hours_id}",
    response_model=BusinessHoursEnvelope,
    summary="Изменить график рабочего времени",
)
async def update_business_hours(
    business_hours_id: uuid.UUID,
    payload: BusinessHoursUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> BusinessHoursEnvelope:
    _require_admin(principal)
    repository = BusinessHoursRepository(session)
    business_hours = await repository.get(business_hours_id)
    if business_hours is None:
        raise ProblemException.not_found(detail="Business hours not found")
    business_hours = await repository.update(business_hours, payload.model_dump(exclude_unset=True))
    await session.commit()
    await session.refresh(business_hours)
    return BusinessHoursEnvelope(
        data=BusinessHoursRead.model_validate(business_hours),
        request_id=_resolve_request_id(x_request_id),
    )


# --- SLAPolicy ---


@router.get(
    "/sla-policies",
    response_model=SLAPolicyListEnvelope,
    summary="Список SLA-политик",
)
async def list_sla_policies(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> SLAPolicyListEnvelope:
    _require_admin(principal)
    items = await SLAPolicyRepository(session).list_all()
    return SLAPolicyListEnvelope(
        data=[SLAPolicyRead.model_validate(item) for item in items],
        request_id=_resolve_request_id(x_request_id),
    )


@router.post(
    "/sla-policies",
    status_code=status.HTTP_201_CREATED,
    response_model=SLAPolicyEnvelope,
    summary="Создать SLA-политику",
)
async def create_sla_policy(
    payload: SLAPolicyInput,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> SLAPolicyEnvelope:
    _require_admin(principal)
    await _ensure_business_hours_exists(session, payload.business_hours_id)
    policy = await SLAPolicyRepository(session).create(_policy_create_values(payload))
    await session.commit()
    await session.refresh(policy)
    return SLAPolicyEnvelope(
        data=SLAPolicyRead.model_validate(policy),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/sla-policies/{policy_id}",
    response_model=SLAPolicyEnvelope,
    summary="SLA-политика",
)
async def get_sla_policy(
    policy_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> SLAPolicyEnvelope:
    _require_admin(principal)
    policy = await SLAPolicyRepository(session).get(policy_id)
    if policy is None:
        raise ProblemException.not_found(detail="SLA policy not found")
    return SLAPolicyEnvelope(
        data=SLAPolicyRead.model_validate(policy),
        request_id=_resolve_request_id(x_request_id),
    )


@router.patch(
    "/sla-policies/{policy_id}",
    response_model=SLAPolicyEnvelope,
    summary="Изменить SLA-политику",
)
async def update_sla_policy(
    policy_id: uuid.UUID,
    payload: SLAPolicyUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> SLAPolicyEnvelope:
    _require_admin(principal)
    repository = SLAPolicyRepository(session)
    policy = await repository.get(policy_id)
    if policy is None:
        raise ProblemException.not_found(detail="SLA policy not found")
    if "business_hours_id" in payload.model_fields_set:
        await _ensure_business_hours_exists(session, payload.business_hours_id)
    policy = await repository.update(policy, _policy_update_changes(payload))
    await session.commit()
    await session.refresh(policy)
    return SLAPolicyEnvelope(
        data=SLAPolicyRead.model_validate(policy),
        request_id=_resolve_request_id(x_request_id),
    )
