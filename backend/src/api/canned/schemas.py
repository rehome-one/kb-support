"""Pydantic-схемы шаблонов ответов (E6-2 #126; §3.6 ТЗ, ADR-0009).

Контракт — `docs/openapi.yaml` (`CannedResponse`/`CannedResponseInput`/
`CannedResponseUpdate`). ПДн нет (конфигурация шаблонов; ПДн появляются при рендере
#127, на сервере). `type` валидируется доменом `TicketType` на границе API, хранится как
`String` (E1-конвенция). `usage_count` — read-only (инкремент при ответе из шаблона #128).
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from api.tickets.enums import TicketType


class CannedResponseInput(BaseModel):
    """Тело POST /canned-responses. Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    type: TicketType | None = None
    linked_article_slug: str | None = Field(default=None, max_length=512)


class CannedResponseUpdate(BaseModel):
    """Тело PATCH /canned-responses/{id} — частичное обновление. Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    type: TicketType | None = None
    linked_article_slug: str | None = Field(default=None, max_length=512)


class CannedResponseRead(BaseModel):
    """Представление шаблона в ответе (контракт `CannedResponse`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    type: str | None
    linked_article_slug: str | None
    usage_count: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CannedRenderInput(BaseModel):
    """Тело POST /canned-responses/{id}/render — заявка, по которой подставляются переменные."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: uuid.UUID


class CannedRenderResult(BaseModel):
    """Результат рендера шаблона для заявки (текст с подставленными переменными)."""

    rendered_body: str
    linked_article_slug: str | None


class CannedRenderEnvelope(BaseModel):
    """Конверт ответа рендера."""

    data: CannedRenderResult
    request_id: uuid.UUID


class CannedResponseEnvelope(BaseModel):
    """Конверт ответа с одним шаблоном (`ResponseEnvelope`)."""

    data: CannedResponseRead
    request_id: uuid.UUID


class CannedResponseListEnvelope(BaseModel):
    """Конверт ответа со списком шаблонов."""

    data: list[CannedResponseRead]
    request_id: uuid.UUID
