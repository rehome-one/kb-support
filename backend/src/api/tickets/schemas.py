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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from api.tickets.enums import (
    AccessLevel,
    AuthorType,
    TicketCaseState,
    TicketChannel,
    TicketDecision,
    TicketPriority,
    TicketStatus,
    TicketTeam,
    TicketType,
)
from api.tickets.sla_state import (
    SlaStateValue,
    compute_sla_state,
    is_resolution_breached,
)
from api.tickets.state_machine import is_allowed_transition


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


class WebFormTicketCreate(BaseModel):
    """Тело POST /tickets/from-web-form (E7-6, #148). Веб-форма в ЛК rehome.one.

    `channel` и `requester_id` НЕ принимаются от клиента (форсятся сервером:
    channel=WEB_FORM, requester_id из проверенного принципала — anti-spoofing,
    ADR-0010 Решение 2). `attachments` — file_id, загруженные ЛК в kb-files."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=300)
    type: TicketType
    description: str | None = None
    priority: TicketPriority | None = None
    premises_id: uuid.UUID | None = None
    booking_id: uuid.UUID | None = None
    tags: list[str] | None = None
    attachments: list[uuid.UUID] | None = None


class TranscriptTurn(BaseModel):
    """Реплика диалога AI-чата (контракт `TicketFromChat.transcript[]`)."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    at: datetime.datetime | None = None


class TicketFromChat(BaseModel):
    """Тело POST /tickets/from-chat — эскалация из kb-search (контракт `TicketFromChat`).

    `requester_id` обязателен и берётся из тела: вызов m2m (kb-search), принципал —
    SERVICE, не заявитель. Endpoint ограничен `kind=SERVICE` (anti-spoofing, #69).
    """

    model_config = ConfigDict(extra="forbid")

    chat_session_id: uuid.UUID
    requester_id: uuid.UUID
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    type: TicketType | None = None
    transcript: list[TranscriptTurn] | None = None
    premises_id: uuid.UUID | None = None
    booking_id: uuid.UUID | None = None


class EmailIngest(BaseModel):
    """Тело POST /tickets/from-email — приём входящего письма от email-шлюза (E7-3, #145).

    `raw_message` — **base64-кодированное сырое RFC822-письмо** (provisional contract:
    JSON-safe носитель байтов; парсер #144 принимает bytes). Вызов m2m (шлюз → нас),
    принципал — SERVICE; endpoint ограничен `kind=SERVICE` (anti-spoofing: отправитель
    резолвится сервером из письма, не из принципала). Лишние поля запрещены.
    """

    model_config = ConfigDict(extra="forbid")

    raw_message: str = Field(min_length=1)


class TicketUpdate(BaseModel):
    """Тело PATCH /tickets/{id} — частичное обновление (контракт `TicketUpdate`).

    `assignee_id` отсутствует намеренно — назначение через `POST /tickets/{id}/assign`
    (#12), не через PATCH. Лишние поля запрещены.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, min_length=1, max_length=300)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    type: TicketType | None = None
    team: TicketTeam | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None


class TicketSummaryRead(BaseModel):
    """Краткая карточка заявки для списков (контракт `TicketSummary`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    subject: str
    status: TicketStatus
    priority: TicketPriority
    type: TicketType
    channel: TicketChannel
    requester_id: uuid.UUID
    assignee_id: uuid.UUID | None
    team: TicketTeam | None
    first_response_due_at: datetime.datetime | None
    resolution_due_at: datetime.datetime | None
    tags: list[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime

    # Источники расчёта SLA-состояния — НЕ сериализуются (контракт растёт только на
    # sla_state), но доступны computed-полям. default=None — для фикстур/частичных данных.
    first_responded_at: datetime.datetime | None = Field(default=None, exclude=True)
    resolved_at: datetime.datetime | None = Field(default=None, exclude=True)
    sla_paused_at: datetime.datetime | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sla_breached(self) -> bool:
        """Нарушен ли дедлайн решения (с учётом текущей паузы и факта решения, #89)."""
        return is_resolution_breached(
            datetime.datetime.now(datetime.UTC),
            resolution_due_at=self.resolution_due_at,
            resolved_at=self.resolved_at,
            sla_paused_at=self.sla_paused_at,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sla_state(self) -> SlaStateValue:
        """Состояние SLA для индикации (FR-4.3): none/ok/approaching/breached (#89)."""
        return compute_sla_state(
            datetime.datetime.now(datetime.UTC),
            created_at=self.created_at,
            first_response_due_at=self.first_response_due_at,
            first_responded_at=self.first_responded_at,
            resolution_due_at=self.resolution_due_at,
            resolved_at=self.resolved_at,
            sla_paused_at=self.sla_paused_at,
        )


class Pagination(BaseModel):
    """Курсорная пагинация (контракт `Pagination`)."""

    next_cursor: str | None
    has_more: bool


class TicketListEnvelope(BaseModel):
    """Конверт ответа со списком кратких карточек + пагинацией."""

    data: list[TicketSummaryRead]
    pagination: Pagination
    request_id: uuid.UUID


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

    # Источник расчёта SLA-состояния (#89) — не сериализуется, доступен computed-полям.
    sla_paused_at: datetime.datetime | None = Field(default=None, exclude=True)

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed_status_transitions(self) -> list[TicketStatus]:
        """Статусы, в которые разрешён переход из текущего (без самого текущего).

        Источник истины — `state_machine.ALLOWED_TRANSITIONS`; экспонируется, чтобы
        фронт подсвечивал недопустимые переходы без дублирования таблицы (#60).
        """
        return [
            status
            for status in TicketStatus
            if status != self.status and is_allowed_transition(self.status, status)
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sla_breached(self) -> bool:
        """Нарушен ли дедлайн решения (с учётом текущей паузы и факта решения, #89)."""
        return is_resolution_breached(
            datetime.datetime.now(datetime.UTC),
            resolution_due_at=self.resolution_due_at,
            resolved_at=self.resolved_at,
            sla_paused_at=self.sla_paused_at,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sla_state(self) -> SlaStateValue:
        """Состояние SLA для индикации (FR-4.3): none/ok/approaching/breached (#89)."""
        return compute_sla_state(
            datetime.datetime.now(datetime.UTC),
            created_at=self.created_at,
            first_response_due_at=self.first_response_due_at,
            first_responded_at=self.first_responded_at,
            resolution_due_at=self.resolution_due_at,
            resolved_at=self.resolved_at,
            sla_paused_at=self.sla_paused_at,
        )


class TicketEnvelope(BaseModel):
    """Конверт успешного ответа с одним тикетом (`ResponseEnvelope`)."""

    data: TicketRead
    request_id: uuid.UUID


class TicketHistoryRead(BaseModel):
    """Строка журнала действий по заявке (ТЗ §3.7)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    actor_id: uuid.UUID
    action: str
    from_value: dict[str, Any] | None
    to_value: dict[str, Any] | None
    created_at: datetime.datetime


class TicketHistoryListEnvelope(BaseModel):
    """Конверт ответа со списком строк журнала."""

    data: list[TicketHistoryRead]
    request_id: uuid.UUID


class AssignInput(BaseModel):
    """Тело POST /tickets/{id}/assign."""

    model_config = ConfigDict(extra="forbid")

    assignee_id: uuid.UUID
    team: TicketTeam | None = None


class EscalateInput(BaseModel):
    """Тело POST /tickets/{id}/escalate."""

    model_config = ConfigDict(extra="forbid")

    team: TicketTeam | None = None
    reason: str | None = None


class ResolveInput(BaseModel):
    """Тело POST /tickets/{id}/resolve."""

    model_config = ConfigDict(extra="forbid")

    resolution_note: str | None = None


class ReopenInput(BaseModel):
    """Тело POST /tickets/{id}/reopen."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class RateInput(BaseModel):
    """Тело POST /tickets/{id}/rate."""

    model_config = ConfigDict(extra="forbid")

    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class CaseStateTransitionInput(BaseModel):
    """Тело POST /tickets/{id}/case-state (контракт transitionCaseState, E10-2)."""

    model_config = ConfigDict(extra="forbid")

    case_state: TicketCaseState
    note: str | None = Field(default=None, max_length=2000)


class DecisionInput(BaseModel):
    """Тело POST /tickets/{id}/decision (контракт decideTicket, E10-3).

    approved_amount обязателен при FULL/PARTIAL, reason — при PARTIAL/REJECTED; условная
    обязательность — доменная (422 в сервисе), не схемная.
    """

    model_config = ConfigDict(extra="forbid")

    decision: TicketDecision
    approved_amount: float | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=4000)


class TicketMessageCreate(BaseModel):
    """Тело POST /tickets/{id}/messages (контракт `TicketMessageCreate`).

    `author_id`/`author_type` НЕ принимаются от клиента — выводятся из принципала
    (anti-spoofing). `canned_response_id` принимается ради контракта; учёт
    usage_count — в E6 (CannedResponse).
    """

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1)
    is_internal: bool = False
    attachments: list[uuid.UUID] | None = None
    canned_response_id: uuid.UUID | None = None


class TicketMessageRead(BaseModel):
    """Сообщение в ответе (контракт `TicketMessage`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    author_id: uuid.UUID | None
    author_type: AuthorType
    body: str
    is_internal: bool
    attachments: list[uuid.UUID]
    created_at: datetime.datetime


class TicketMessageEnvelope(BaseModel):
    """Конверт ответа с одним сообщением."""

    data: TicketMessageRead
    request_id: uuid.UUID


class TicketMessageListEnvelope(BaseModel):
    """Конверт ответа со списком сообщений."""

    data: list[TicketMessageRead]
    request_id: uuid.UUID


# --- Контекст заявителя для карточки оператора (FR-2.2, enabler #81). ---
# Это НАШИ схемы ответа kb-support: маппинг из доменных DTO platform-клиента (#71),
# а не провизорная форма rehome.one. Все секции nullable (сущности нет/сосед недоступен).


class RequesterUserRead(BaseModel):
    """Профиль заявителя (из platform UserProfile DTO)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str | None
    phone: str | None
    role: str
    is_active: bool
    created_at: datetime.datetime | None


class RequesterPremisesRead(BaseModel):
    """Объект (квартира/помещение) по заявке (из platform Premises DTO)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    address: str
    kind: str
    rooms: int | None
    area_m2: float | None
    landlord_id: uuid.UUID | None


class RequesterBookingRead(BaseModel):
    """Бронь/договор найма по заявке (из platform Booking DTO)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    premises_id: uuid.UUID
    tenant_id: uuid.UUID
    landlord_id: uuid.UUID
    status: str
    period_start: datetime.date
    period_end: datetime.date | None
    monthly_rent: float | None


class RequesterContactRead(BaseModel):
    """Контакты коллаборанта (из platform Contact DTO)."""

    model_config = ConfigDict(from_attributes=True)

    email: str | None
    phone: str | None


class RequesterCollaboratorRead(BaseModel):
    """Коллаборант по заявке (из platform Collaborator DTO)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    contact: RequesterContactRead | None
    is_active: bool


class RequesterContextRead(BaseModel):
    """Контекст заявителя на карточке оператора (FR-2.2). Секции независимы и nullable.

    `degraded=true` — интеграция с platform не сконфигурирована (пустой токен, см. #77);
    это про доступность интеграции, не про существование сущности.
    """

    user: RequesterUserRead | None
    premises: RequesterPremisesRead | None
    booking: RequesterBookingRead | None
    collaborator: RequesterCollaboratorRead | None
    degraded: bool


class RequesterContextEnvelope(BaseModel):
    """Конверт ответа с контекстом заявителя."""

    data: RequesterContextRead
    request_id: uuid.UUID
