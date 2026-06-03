"""ORM-модель Ticket — центральная сущность kb-support (ТЗ v2.2 §3.1).

Базовая версия E1. Поля претензионных типов (§3.1.1: case_state, claim_amount,
decision, ... ) и связанная сущность TicketCaseDetails (§3.11) НЕ включены —
это E10 (#23), добавятся отдельной миграцией.

Перечисления домена — в `api.tickets.enums`; в БД хранятся как `String`
(решение Архитектора 2026-05-30, Issue #5: настраиваемые справочники §3.2/§3.3,
без нативного PG ENUM).

**Архитектурная константа (§3.10, NFR-4.4, ADR-0005).** Ссылочные идентификаторы
`requester_id` / `assignee_id` / `premises_id` / `booking_id` / `collaborator_id`
/ `service_order_id` / `chat_session_id` указывают на сущности в rehome.one и
rehome-kb-platform, которые доступны ТОЛЬКО по HTTP API. Поэтому это обычные
UUID-колонки БЕЗ `ForeignKey` — никаких FK к чужим таблицам, никаких shared
таблиц. `sla_policy_id` станет FK на собственную таблицу `sla_policies` в E4.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import ARRAY, DateTime, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, TimestampMixin
from api.tickets.enums import AccessLevel, TicketPriority, TicketStatus


class Ticket(TimestampMixin, Base):
    """Обращение (Ticket) — ТЗ §3.1."""

    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("number", name="uq_tickets_number"),
        Index("ix_tickets_requester_id", "requester_id"),
        Index("ix_tickets_assignee_id", "assignee_id"),
        Index("ix_tickets_status_created_at", "status", "created_at"),
        # Частичный uniq: не более одной АКТИВНОЙ (не CLOSED) заявки на chat_session_id
        # — идемпотентность эскалации из чата + защита от гонки параллельных вызовов
        # (E3-1, #69). Re-эскалация после закрытия разрешена (status='CLOSED' вне
        # индекса). Служит и быстрым lookup'ом для дедупа.
        Index(
            "uq_tickets_active_chat_session",
            "chat_session_id",
            unique=True,
            postgresql_where=text("chat_session_id IS NOT NULL AND status <> 'CLOSED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    # Человекочитаемый номер RH-YYYY-NNNNN. Генерация — в #6 (POST); здесь только
    # колонка + unique-ограничение.
    number: Mapped[str] = mapped_column(String(32), nullable=False)

    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)

    # --- Доменные справочники (String + app-валидация, Issue #5) ---
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TicketStatus.NEW.value)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TicketPriority.NORMAL.value
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    team: Mapped[str | None] = mapped_column(String(16), nullable=True)
    access_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AccessLevel.LOGGED.value
    )

    # --- Ссылки на сущности платформы: UUID без ForeignKey (арх-константа §3.10) ---
    requester_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    premises_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    collaborator_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    service_order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    chat_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    # FK на собственную sla_policies появится в E4 — пока обычный UUID.
    sla_policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)

    # --- SLA-дедлайны и факты (заполняются в E4 / при работе оператора) ---
    first_response_due_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_due_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_responded_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Учёт пауз SLA (E4-4 #88, FR-4.5 / ADR-0007 Решение 2: паузы = PENDING+WAITING) ---
    # Начало ТЕКУЩЕЙ паузы (null = заявка не на паузе); накопленная длительность пауз — для
    # сдвига resolution_due_at на выходе из паузы и аудита (E8). first_response_due_at паузами
    # не двигается.
    sla_paused_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_paused_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    reopened_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default=text("'{}'")
    )
    custom_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # --- Оценка качества (E9 — колонки есть, логика позже) ---
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_comment: Mapped[str | None] = mapped_column(Text(), nullable=True)

    def __repr__(self) -> str:
        return f"<Ticket id={self.id!r} number={self.number!r} status={self.status!r}>"
