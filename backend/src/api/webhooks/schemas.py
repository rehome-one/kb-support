"""Pydantic-схемы webhook-подписок (E10-8 PR-A #198; контракт `WebhookSubscription`).

Контракт — `docs/openapi.yaml` (`WebhookSubscription`). **ADR-0015 У6 / ФЗ-152:** `secret`
возвращается ТОЛЬКО при создании (`WebhookSubscriptionCreated`); в списке (`...Read`) его нет.
`events` валидируется доменом `WebhookEvent` на границе API, хранится как список строк.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from api.tickets.enums import InsurerDecision
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


class InsurerEventIngest(BaseModel):
    """Тело inbound webhook страховщика (E10-8 PR-C #198 / E10-10 PR-C #200, провизорно).

    `ticket_number` — наш человекочитаемый номер заявки (страховщик знал его из outbound);
    `insurance_event_id` — id страхового события на стороне страховщика. **E10-10 (ADR-0017 D2):**
    опц. `insurer_status` (статусный лейбл страховщика → `InsurancePayload.insurer_status`) и
    `insurer_decision` (вердикт → системный сдвиг case_state). Оба опциональны — обратная
    совместимость с чистым приёмом E10-8. Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    ticket_number: str = Field(min_length=1, max_length=64)
    insurance_event_id: uuid.UUID
    insurer_status: str | None = Field(default=None, min_length=1, max_length=128)
    insurer_decision: InsurerDecision | None = None


class GuaranteeEventIngest(BaseModel):
    """Тело inbound сигнала платёжного контура о гарантийном исключении (E10-10 PR-A; ADR-0017 D1).

    Системно создаёт GUARANTEE-тикет при исключениях (5.7.6/7/8). `reference` — id сигнала
    upstream (идемпотентность). Регресс-поля — ССЫЛКИ (деньги/пеню не считаем, D2). extra=forbid."""

    model_config = ConfigDict(extra="forbid")

    exception_kind: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=128)
    requester_id: uuid.UUID | None = None
    missed_payment_id: uuid.UUID | None = None
    regress_obligation_id: uuid.UUID | None = None
    late_fee_accrued: float | None = Field(default=None, ge=0)
