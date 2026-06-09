"""Admin-CRUD webhook-подписок (E10-8 PR-A #198; ADR-0015 D2; контракт listWebhooks/createWebhook).

RBAC (контракт: `scope=staff_admin`): и список, и создание — только `staff_admin`, иначе 403.
scope считается бэкендом из проверенного JWT (CLAUDE.md: не из payload/фронта). ПДн нет
(конфигурация доставки). `secret` отдаётся только при создании, в списке отсутствует (ADR-0015 У6).
Только свои таблицы (арх-константа). Эмиссия событий по этим подпискам — PR-B.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.db import get_session
from api.errors import ProblemException
from api.webhooks.repository import WebhookSubscriptionRepository
from api.webhooks.schemas import (
    WebhookSubscriptionCreated,
    WebhookSubscriptionCreatedEnvelope,
    WebhookSubscriptionInput,
    WebhookSubscriptionListEnvelope,
    WebhookSubscriptionRead,
)

router = APIRouter(prefix="/api/v1/support", tags=["Webhooks"])

_GENERATED_SECRET_BYTES = 32  # → 64 hex-символа, надёжный HMAC-секрет


def _require_admin(principal: Principal) -> None:
    """RBAC: webhook-подписки — скоуп `staff_admin`, иначе 403 (контракт)."""
    if not principal.is_staff_admin:
        raise ProblemException.forbidden(detail="Staff admin scope required")


def _resolve_request_id(raw: str | None) -> uuid.UUID:
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


def _create_values(payload: WebhookSubscriptionInput) -> dict[str, Any]:
    """Колонки подписки. `secret` не передан → генерируем (token_hex)."""
    return {
        "url": str(payload.url),
        "events": [event.value for event in payload.events],
        "secret": payload.secret or secrets.token_hex(_GENERATED_SECRET_BYTES),
        "is_active": payload.is_active,
    }


@router.get(
    "/webhooks",
    response_model=WebhookSubscriptionListEnvelope,
    summary="Список подписок",
)
async def list_webhooks(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> WebhookSubscriptionListEnvelope:
    _require_admin(principal)
    items = await WebhookSubscriptionRepository(session).list()
    return WebhookSubscriptionListEnvelope(
        data=[WebhookSubscriptionRead.model_validate(item) for item in items],
        request_id=_resolve_request_id(x_request_id),
    )


@router.post(
    "/webhooks",
    status_code=status.HTTP_201_CREATED,
    response_model=WebhookSubscriptionCreatedEnvelope,
    summary="Зарегистрировать webhook",
)
async def create_webhook(
    payload: WebhookSubscriptionInput,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> WebhookSubscriptionCreatedEnvelope:
    _require_admin(principal)
    subscription = await WebhookSubscriptionRepository(session).create(_create_values(payload))
    await session.commit()
    await session.refresh(subscription)
    return WebhookSubscriptionCreatedEnvelope(
        data=WebhookSubscriptionCreated.model_validate(subscription),
        request_id=_resolve_request_id(x_request_id),
    )
