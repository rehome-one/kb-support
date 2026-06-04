"""Pydantic-схемы admin CRUD автоматизации (E5-2 #104, §6 ТЗ; ADR-0008 Реш.1/7).

Контракт — `docs/openapi.yaml` (`AutomationRule`/`AutomationRuleInput`/
`AutomationRuleUpdate`). ПДн нет — конфигурация правил. На границе API валидируем
типизированно; в БД `conditions`/`actions` хранятся как JSONB (паттерн
`SLAPolicy.applies_to` #86).

**conditions** — конъюнкция typed-полей; отсутствует/пусто = wildcard (ADR-0008 Реш.1).
**actions** — дискриминированный union по `action` (envelope `{action, params}`),
`params` типизирован на действие. notify/create_service_order — seam'ы (доставка — E7;
заказ коллаборанта — platform/#77), их params — опциональные, помечены `# seam`.
**`order`** контракта ↔ колонка `apply_order` (#103): alias на чтении/записи.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.automation.enums import (
    AssignStrategy,
    AutomationActionType,
    AutomationTrigger,
    NotifyRecipient,
)
from api.tickets.enums import TicketChannel, TicketPriority, TicketStatus, TicketTeam, TicketType


class AutomationConditions(BaseModel):
    """Условия применения правила (контракт `AutomationConditions`).

    Все поля опциональны; None/пустой список = wildcard (условие не ограничивает).
    Пустой объект = правило применяется ко всем заявкам триггера. keywords —
    подстрочный case-insensitive матчинг по subject/description (ADR-0008 Реш.2, #105)."""

    model_config = ConfigDict(extra="forbid")

    types: list[TicketType] | None = None
    priorities: list[TicketPriority] | None = None
    channels: list[TicketChannel] | None = None
    keywords: list[str] | None = None


# --- Параметры действий (per-action params, ADR-0008 Реш.1) ---


class AssignParams(BaseModel):
    """params действия assign. direct → нужен operator_id; стратегии → нужна team
    (пул операторов из команды + опц. `pool`-seam #77; least_load — live-query #109)."""

    model_config = ConfigDict(extra="forbid")

    strategy: AssignStrategy
    operator_id: uuid.UUID | None = None
    team: TicketTeam | None = None
    pool: list[uuid.UUID] | None = None  # seam #77 (явный пул до platform-источника)

    @model_validator(mode="after")
    def _check_strategy_fields(self) -> AssignParams:
        if self.strategy == AssignStrategy.DIRECT and self.operator_id is None:
            raise ValueError("assign.direct требует operator_id")
        if self.strategy != AssignStrategy.DIRECT and self.team is None:
            raise ValueError(f"assign.{self.strategy.value} требует team")
        return self


class SetStatusParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TicketStatus


class SetPriorityParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: TicketPriority


class AddTagParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(min_length=1)


class EscalateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team: TicketTeam | None = None  # опц. смена команды при эскалации


class NotifyParams(BaseModel):
    """seam (ADR-0008 Реш.3): форма зафиксирована, доставка — E7 (config-gated)."""

    model_config = ConfigDict(extra="forbid")
    recipient: NotifyRecipient
    channel: str | None = None  # seam: канал доставки (email/push/...) — E7
    template: str | None = None  # seam: шаблон уведомления — E7


class CreateServiceOrderParams(BaseModel):
    """seam (ADR-0008 Реш.3): боевой путь — platform/#77 (config-gated)."""

    model_config = ConfigDict(extra="forbid")
    collaborator_category: str | None = None  # seam #77
    premises_id: uuid.UUID | None = None  # seam #77


# --- Действия (envelope {action, params}, дискриминатор `action`) ---


class AssignAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[AutomationActionType.ASSIGN]
    params: AssignParams


class SetStatusAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[AutomationActionType.SET_STATUS]
    params: SetStatusParams


class SetPriorityAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[AutomationActionType.SET_PRIORITY]
    params: SetPriorityParams


class AddTagAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[AutomationActionType.ADD_TAG]
    params: AddTagParams


class EscalateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[AutomationActionType.ESCALATE]
    params: EscalateParams = Field(default_factory=EscalateParams)


class NotifyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[AutomationActionType.NOTIFY]
    params: NotifyParams


class CreateServiceOrderAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[AutomationActionType.CREATE_SERVICE_ORDER]
    params: CreateServiceOrderParams = Field(default_factory=CreateServiceOrderParams)


AutomationActionModel = Annotated[
    AssignAction
    | SetStatusAction
    | SetPriorityAction
    | AddTagAction
    | EscalateAction
    | NotifyAction
    | CreateServiceOrderAction,
    Field(discriminator="action"),
]


# --- Конверты CRUD ---


class AutomationRuleInput(BaseModel):
    """Тело POST /automation-rules (контракт `AutomationRuleInput`). Лишние поля запрещены.

    `order` — alias колонки `apply_order` (#103). `actions` — минимум одно действие
    (правило без действий бессмысленно)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    trigger: AutomationTrigger
    conditions: AutomationConditions = Field(default_factory=AutomationConditions)
    actions: list[AutomationActionModel] = Field(min_length=1)
    is_active: bool = True
    order: int = 0


class AutomationRuleUpdate(BaseModel):
    """Тело PATCH /automation-rules/{id} — частичное обновление. Лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    trigger: AutomationTrigger | None = None
    conditions: AutomationConditions | None = None
    actions: list[AutomationActionModel] | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    order: int | None = None


class AutomationRuleRead(BaseModel):
    """Представление правила в ответе (контракт `AutomationRule`).

    `conditions`/`actions` отдаются ровно как сохранены (dict/list без null-ключей —
    конформит контракту). `order` ← колонка `apply_order`."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    name: str
    trigger: str
    conditions: dict[str, Any]
    actions: list[Any]
    is_active: bool
    # Колонка #103 — `apply_order`; в контракте поле `order` (read из ORM-атрибута).
    order: int = Field(validation_alias="apply_order")
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AutomationRuleEnvelope(BaseModel):
    """Конверт ответа с одним правилом (`ResponseEnvelope`)."""

    data: AutomationRuleRead
    request_id: uuid.UUID


class AutomationRuleListEnvelope(BaseModel):
    """Конверт ответа со списком правил."""

    data: list[AutomationRuleRead]
    request_id: uuid.UUID
