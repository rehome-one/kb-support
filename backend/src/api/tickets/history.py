"""Неизменяемый журнал действий по заявке — TicketHistory (ТЗ §3.7, NFR-1.4, ФЗ-152).

Каждое значимое действие (создание, смена статуса, переназначение, ...) пишется
отдельной строкой. Записи **неизменяемы**: UPDATE/DELETE по `ticket_history`
нигде в коде не выполняются (основание для разбора споров, хранение 5 лет —
`Settings.history_retention_days`; cleanup-воркер — отдельный Issue в E8).

`ticket_id` — FK на СВОЮ таблицу `tickets` (арх-константа запрещает FK только к
чужим БД). `actor_id` — `sub` из токена (ссылка на User платформы, не FK).
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class TicketHistoryAction(str, enum.Enum):
    """Виды действий в журнале заявки (ТЗ §3.7). Хранятся как String."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    REASSIGNED = "reassigned"
    PRIORITY_CHANGED = "priority_changed"
    TYPE_CHANGED = "type_changed"
    TEAM_CHANGED = "team_changed"
    TAGS_UPDATED = "tags_updated"
    MESSAGE_ADDED = "message_added"
    RATED = "rated"


class TicketHistory(Base):
    """Строка журнала действий по заявке (неизменяемая)."""

    __tablename__ = "ticket_history"
    __table_args__ = (
        # Композитный индекс обслуживает выборку истории заявки в порядке
        # created_at DESC (backward index scan).
        Index("ix_ticket_history_ticket_id_created_at", "ticket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("tickets.id", name="fk_ticket_history_ticket_id"), nullable=False
    )
    # Кто совершил действие — sub из токена (не из payload). null — для системных
    # событий (SYSTEM) в будущем; на E1 всегда заполнен.
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    to_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # timezone=True → UTC. updated_at нет: записи неизменяемы.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<TicketHistory ticket_id={self.ticket_id!r} action={self.action!r}>"


class HistoryRecorder(Protocol):
    """Контракт записи в журнал (для декаплинга diff-логики от хранилища)."""

    async def record(
        self,
        ticket_id: uuid.UUID,
        actor_id: uuid.UUID,
        action: TicketHistoryAction,
        *,
        from_value: dict[str, Any] | None = None,
        to_value: dict[str, Any] | None = None,
    ) -> None: ...


class TicketHistoryRepository:
    """Запись и чтение журнала заявки поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        ticket_id: uuid.UUID,
        actor_id: uuid.UUID,
        action: TicketHistoryAction,
        *,
        from_value: dict[str, Any] | None = None,
        to_value: dict[str, Any] | None = None,
    ) -> None:
        """Добавить неизменяемую строку журнала (commit — на стороне вызывающего)."""
        self._session.add(
            TicketHistory(
                ticket_id=ticket_id,
                actor_id=actor_id,
                action=action.value,
                from_value=from_value,
                to_value=to_value,
            )
        )
        await self._session.flush()

    async def list_for_ticket(self, ticket_id: uuid.UUID) -> Sequence[TicketHistory]:
        """Журнал заявки в порядке created_at DESC (новые сверху)."""
        stmt = (
            select(TicketHistory)
            .where(TicketHistory.ticket_id == ticket_id)
            .order_by(TicketHistory.created_at.desc(), TicketHistory.id.desc())
        )
        return (await self._session.execute(stmt)).scalars().all()


def _to_jsonable(value: Any) -> Any:
    """Привести значение поля к JSON-совместимому виду для JSONB."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    return value


# Поле заявки → действие журнала при его изменении.
# assignee_id → reassigned триггерится из /assign (#12), не из PATCH.
_FIELD_ACTIONS: dict[str, TicketHistoryAction] = {
    "status": TicketHistoryAction.STATUS_CHANGED,
    "assignee_id": TicketHistoryAction.REASSIGNED,
    "priority": TicketHistoryAction.PRIORITY_CHANGED,
    "type": TicketHistoryAction.TYPE_CHANGED,
    "team": TicketHistoryAction.TEAM_CHANGED,
    "tags": TicketHistoryAction.TAGS_UPDATED,
}


async def record_changes(
    recorder: HistoryRecorder,
    ticket_id: uuid.UUID,
    actor_id: uuid.UUID,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    """Записать в журнал изменения отслеживаемых полей (diff before→after).

    Используется обновляющими путями (PATCH/actions — #8/#12). Пишет по одной
    строке на каждое реально изменившееся отслеживаемое поле.
    """
    for field, action in _FIELD_ACTIONS.items():
        if field in before and field in after and before[field] != after[field]:
            await recorder.record(
                ticket_id,
                actor_id,
                action,
                from_value={field: _to_jsonable(before[field])},
                to_value={field: _to_jsonable(after[field])},
            )
