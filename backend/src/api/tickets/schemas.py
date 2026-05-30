"""Pydantic-схемы запросов/ответов для эндпоинтов тикетов (контракт `04_openapi.yaml`).

`TicketCreate` — тело POST. `TicketRead` — представление `Ticket` в ответе
(повторяет контрактную схему `Ticket`). `TicketEnvelope` — конверт успешного
ответа (`{data, request_id}`, схема `ResponseEnvelope`).

Поля претензионных типов (§3.1.1) на E1 всегда `null` — модель их ещё не хранит
(E10), но они присутствуют в ответе для совместимости с контрактом.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.tickets.enums import (
    AccessLevel,
    TicketChannel,
    TicketPriority,
    TicketStatus,
    TicketTeam,
    TicketType,
)


class TicketCreate(BaseModel):
    """Тело POST /tickets (контракт `TicketCreate`). Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=300)
    type: TicketType
    description: str | None = None
    priority: TicketPriority | None = None
    channel: TicketChannel | None = None
    # Заполняется только оператором (создание от имени заявителя). Для заявителя
    # игнорируется — requester_id берётся из принципала (anti-spoofing).
    requester_id: uuid.UUID | None = None
    premises_id: uuid.UUID | None = None
    booking_id: uuid.UUID | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None


class TicketRead(BaseModel):
    """Представление заявки в ответе (контракт `Ticket`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    subject: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    type: TicketType
    channel: TicketChannel
    requester_id: uuid.UUID
    assignee_id: uuid.UUID | None
    team: TicketTeam | None
    premises_id: uuid.UUID | None
    booking_id: uuid.UUID | None
    collaborator_id: uuid.UUID | None
    service_order_id: uuid.UUID | None
    chat_session_id: uuid.UUID | None
    sla_policy_id: uuid.UUID | None
    first_response_due_at: datetime.datetime | None
    resolution_due_at: datetime.datetime | None
    first_responded_at: datetime.datetime | None
    resolved_at: datetime.datetime | None
    closed_at: datetime.datetime | None
    reopened_count: int
    tags: list[str]
    custom_fields: dict[str, Any]
    access_level: AccessLevel
    rating: int | None
    rating_comment: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    # --- Поля претензионных типов (§3.1.1) — всегда null на E1 (E10 наполнит) ---
    case_state: str | None = None
    claim_amount: float | None = None
    approved_amount: float | None = None
    decision: str | None = None
    decision_reason: str | None = None
    decision_notified_at: datetime.datetime | None = None
    payout_due_at: datetime.datetime | None = None
    linked_payment_id: uuid.UUID | None = None
    regress_obligation_id: uuid.UUID | None = None
    policy_id: uuid.UUID | None = None
    insurance_event_id: uuid.UUID | None = None
    acceptance_act_id: uuid.UUID | None = None
    case_details: dict[str, Any] | None = None


class TicketEnvelope(BaseModel):
    """Конверт успешного ответа с одним тикетом (`ResponseEnvelope`)."""

    data: TicketRead
    request_id: uuid.UUID
