"""CRUD-эндпоинты шаблонов ответов (E6-2 #126; FR-5.1, §3.6 ТЗ, ADR-0009).

RBAC (ADR-0009 Решение 4): **CRUD** (POST/PATCH) — скоуп `staff_support`; **чтение**
(list/get) — любой оператор (нужно для вставки шаблона, FR-2.5); заявитель → 403. ПДн нет
(конфигурация; ПДн при рендере #127). Только свои таблицы (арх-константа).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.canned.repository import CannedResponseRepository
from api.canned.schemas import (
    CannedResponseEnvelope,
    CannedResponseInput,
    CannedResponseListEnvelope,
    CannedResponseRead,
    CannedResponseUpdate,
)
from api.db import get_session
from api.errors import ProblemException
from api.tickets.enums import TicketType

router = APIRouter(prefix="/api/v1/support", tags=["Canned Responses"])


def _require_operator(principal: Principal) -> None:
    """RBAC: список/чтение шаблонов — операторам (заявитель → 403)."""
    if not principal.is_operator:
        raise ProblemException.forbidden(detail="Operator access required")


def _require_support(principal: Principal) -> None:
    """RBAC: CRUD шаблонов — скоуп `staff_support`, иначе 403 (FR-5.1, ADR-0009)."""
    if not principal.is_staff_support:
        raise ProblemException.forbidden(detail="Staff support scope required")


def _resolve_request_id(raw: str | None) -> uuid.UUID:
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


def _create_values(payload: CannedResponseInput) -> dict[str, Any]:
    return {
        "title": payload.title,
        "body": payload.body,
        "type": payload.type.value if payload.type is not None else None,
        "linked_article_slug": payload.linked_article_slug,
    }


def _update_changes(payload: CannedResponseUpdate) -> dict[str, Any]:
    """Только переданные поля; `type`-enum → строковое значение колонки."""
    fields = payload.model_fields_set
    changes: dict[str, Any] = {}
    if "title" in fields:
        changes["title"] = payload.title
    if "body" in fields:
        changes["body"] = payload.body
    if "type" in fields:
        changes["type"] = payload.type.value if payload.type is not None else None
    if "linked_article_slug" in fields:
        changes["linked_article_slug"] = payload.linked_article_slug
    return changes


@router.get(
    "/canned-responses",
    response_model=CannedResponseListEnvelope,
    summary="Список шаблонов ответов",
)
async def list_canned_responses(
    type: TicketType | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> CannedResponseListEnvelope:
    _require_operator(principal)
    items = await CannedResponseRepository(session).list(
        type_filter=type.value if type is not None else None
    )
    return CannedResponseListEnvelope(
        data=[CannedResponseRead.model_validate(item) for item in items],
        request_id=_resolve_request_id(x_request_id),
    )


@router.post(
    "/canned-responses",
    status_code=status.HTTP_201_CREATED,
    response_model=CannedResponseEnvelope,
    summary="Создать шаблон ответа",
)
async def create_canned_response(
    payload: CannedResponseInput,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> CannedResponseEnvelope:
    _require_support(principal)
    canned = await CannedResponseRepository(session).create(_create_values(payload))
    await session.commit()
    await session.refresh(canned)
    return CannedResponseEnvelope(
        data=CannedResponseRead.model_validate(canned),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/canned-responses/{canned_id}",
    response_model=CannedResponseEnvelope,
    summary="Шаблон ответа",
)
async def get_canned_response(
    canned_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> CannedResponseEnvelope:
    _require_operator(principal)
    canned = await CannedResponseRepository(session).get(canned_id)
    if canned is None:
        raise ProblemException.not_found(detail="Canned response not found")
    return CannedResponseEnvelope(
        data=CannedResponseRead.model_validate(canned),
        request_id=_resolve_request_id(x_request_id),
    )


@router.patch(
    "/canned-responses/{canned_id}",
    response_model=CannedResponseEnvelope,
    summary="Изменить шаблон ответа",
)
async def update_canned_response(
    canned_id: uuid.UUID,
    payload: CannedResponseUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> CannedResponseEnvelope:
    _require_support(principal)
    repository = CannedResponseRepository(session)
    canned = await repository.get(canned_id)
    if canned is None:
        raise ProblemException.not_found(detail="Canned response not found")
    canned = await repository.update(canned, _update_changes(payload))
    await session.commit()
    await session.refresh(canned)
    return CannedResponseEnvelope(
        data=CannedResponseRead.model_validate(canned),
        request_id=_resolve_request_id(x_request_id),
    )
