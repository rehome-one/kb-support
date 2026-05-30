"""Переписка по заявке — TicketMessage (ТЗ §3.5, NFR-1.3).

**Критичный инвариант NFR-1.3:** сообщения с `is_internal=true` (внутренние
заметки операторов) НЕ видны заявителю — фильтрация на уровне SQL-запроса
(`list_for_principal`), не в Python. `author_id`/`author_type` выводятся из
принципала (не из payload — anti-spoofing). `ticket_id` — FK на свою `tickets`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from api.auth.principal import Principal
from api.db.base import Base
from api.tickets.enums import AuthorType


class TicketMessage(Base):
    """Сообщение в переписке заявки (ТЗ §3.5)."""

    __tablename__ = "ticket_messages"
    __table_args__ = (Index("ix_ticket_messages_ticket_id_created_at", "ticket_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("tickets.id", name="fk_ticket_messages_ticket_id"), nullable=False
    )
    # null — для system/ai сообщений (E3/E16); для requester/operator — sub токена.
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    author_type: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    is_internal: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false"
    )
    # Массив id вложений в kb-files (интеграция — E7).
    attachments: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<TicketMessage ticket_id={self.ticket_id!r} is_internal={self.is_internal!r}>"


class TicketMessageRepository:
    """Создание и чтение сообщений с фильтром видимости (NFR-1.3)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        ticket_id: uuid.UUID,
        principal: Principal,
        *,
        body: str,
        is_internal: bool,
        attachments: list[uuid.UUID] | None,
    ) -> TicketMessage:
        """Создать сообщение. Автор выводится из принципала (anti-spoofing)."""
        author_type = AuthorType.OPERATOR if principal.is_operator else AuthorType.REQUESTER
        message = TicketMessage(
            ticket_id=ticket_id,
            author_id=principal.user_id,
            author_type=author_type.value,
            body=body,
            is_internal=is_internal,
            attachments=[str(file_id) for file_id in (attachments or [])],
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_for_principal(
        self, ticket_id: uuid.UUID, principal: Principal
    ) -> Sequence[TicketMessage]:
        """Сообщения заявки в хронологическом порядке.

        Заявителю внутренние заметки (`is_internal=true`) исключаются на уровне
        SQL (NFR-1.3); оператор видит все.
        """
        stmt = select(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
        if not principal.is_operator:
            stmt = stmt.where(TicketMessage.is_internal.is_(False))
        stmt = stmt.order_by(TicketMessage.created_at, TicketMessage.id)
        return (await self._session.execute(stmt)).scalars().all()


def message_added_payload(message: TicketMessage) -> dict[str, Any]:
    """to_value для записи истории `message_added` (§3.7)."""
    return {"message_id": str(message.id), "is_internal": message.is_internal}
