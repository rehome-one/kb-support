"""Pydantic-схемы webhook-подписок (E10-8 PR-A #198; контракт `WebhookSubscription`).

Контракт — `docs/openapi.yaml` (`WebhookSubscription`). **ADR-0015 У6 / ФЗ-152:** `secret`
возвращается ТОЛЬКО при создании (`WebhookSubscriptionCreated`); в списке (`...Read`) его нет.
`events` валидируется доменом `WebhookEvent` на границе API, хранится как список строк.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from api.webhooks.enums import WebhookEvent


class WebhookSubscriptionInput(BaseModel):
    """Тело POST /webhooks. Лишние поля запрещены.

    `secret` опционален: если не передан — генерируется сервером (роутер) и возвращается
    один раз в ответе создания."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    events: list[WebhookEvent] = Field(min_length=1)
    secret: str | None = Field(default=None, min_length=16, max_length=256)
    is_active: bool = True


class WebhookSubscriptionRead(BaseModel):
    """Представление подписки в списке/ответах БЕЗ секрета (ADR-0015 У6)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class WebhookSubscriptionCreated(WebhookSubscriptionRead):
    """Ответ создания: `Read` + секрет (отдаётся один раз; контракт «только при создании»)."""

    secret: str


class WebhookSubscriptionListEnvelope(BaseModel):
    """Конверт ответа со списком подписок."""

    data: list[WebhookSubscriptionRead]
    request_id: uuid.UUID


class WebhookSubscriptionCreatedEnvelope(BaseModel):
    """Конверт ответа создания (с секретом)."""

    data: WebhookSubscriptionCreated
    request_id: uuid.UUID
