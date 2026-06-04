"""Короткие action-операции над заявкой (#12) — service-слой.

assign / escalate / resolve / close / reopen / rate. Каждая — изменение
поля/статуса + запись в TicketHistory (§3.7), поверх машины состояний (#8).

Видимость заявки (404) и RBAC (403) проверяются в роутере ДО вызова; здесь —
доменная логика: запрещённый переход статуса → 409 (Conflict, как в контракте
для actions); недопустимое состояние для оценки → 422.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.errors import ProblemException
from api.tickets.enums import TicketStatus, TicketTeam
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.repository import apply_status_side_effects
from api.tickets.state_machine import is_allowed_transition

# Оценка заявителя возможна только в терминальных состояниях.
_RATEABLE_STATUSES = frozenset({TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value})


class TicketActionService:
    """Доменные операции action-эндпоинтов. Commit — на стороне вызывающего."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._history = TicketHistoryRepository(session)

    async def _transition(
        self,
        ticket: Ticket,
        target: TicketStatus,
        actor_id: uuid.UUID,
        *,
        extra: dict[str, str] | None = None,
    ) -> None:
        current = TicketStatus(ticket.status)
        if not is_allowed_transition(current, target):
            raise ProblemException.conflict(
                detail=f"Status transition {current.value} → {target.value} is not allowed"
            )
        ticket.status = target.value
        apply_status_side_effects(ticket, current.value)
        await self._session.flush()
        to_value: dict[str, object] = {"status": target.value}
        if extra:
            to_value.update(extra)
        await self._history.record(
            ticket.id,
            actor_id,
            TicketHistoryAction.STATUS_CHANGED,
            from_value={"status": current.value},
            to_value=to_value,
        )

    async def transition(
        self,
        ticket: Ticket,
        target: TicketStatus,
        actor_id: uuid.UUID,
        *,
        extra: dict[str, str] | None = None,
    ) -> None:
        """Публичный переход статуса (валидация + side-effects + history).

        Тонкая обёртка над `_transition` для переиспользования вне action-эндпоинтов
        (движок автоматизации #106): запрещённый переход → 409 (ловится вызывающим)."""
        await self._transition(ticket, target, actor_id, extra=extra)

    async def assign(
        self,
        ticket: Ticket,
        actor_id: uuid.UUID,
        *,
        assignee_id: uuid.UUID,
        team: TicketTeam | None,
        extra: dict[str, str] | None = None,
    ) -> None:
        """Назначить исполнителя (и опционально команду). Статус не меняется.

        `extra` (опц.) — доп. метки в `to_value` (напр. `automation_rule_id` #106)."""
        previous = ticket.assignee_id
        ticket.assignee_id = assignee_id
        if team is not None:
            ticket.team = team.value
        await self._session.flush()
        to_value: dict[str, object] = {"assignee_id": str(assignee_id), "team": ticket.team}
        if extra:
            to_value.update(extra)
        await self._history.record(
            ticket.id,
            actor_id,
            TicketHistoryAction.REASSIGNED,
            from_value={"assignee_id": str(previous) if previous is not None else None},
            to_value=to_value,
        )

    async def escalate(
        self,
        ticket: Ticket,
        actor_id: uuid.UUID,
        *,
        team: TicketTeam | None,
        reason: str | None,
    ) -> None:
        if team is not None:
            ticket.team = team.value
        await self._transition(
            ticket,
            TicketStatus.ESCALATED,
            actor_id,
            extra={"reason": reason} if reason else None,
        )

    async def resolve(
        self, ticket: Ticket, actor_id: uuid.UUID, *, resolution_note: str | None
    ) -> None:
        await self._transition(
            ticket,
            TicketStatus.RESOLVED,
            actor_id,
            extra={"resolution_note": resolution_note} if resolution_note else None,
        )

    async def close(self, ticket: Ticket, actor_id: uuid.UUID) -> None:
        await self._transition(ticket, TicketStatus.CLOSED, actor_id)

    async def reopen(self, ticket: Ticket, actor_id: uuid.UUID, *, reason: str | None) -> None:
        await self._transition(
            ticket,
            TicketStatus.REOPENED,
            actor_id,
            extra={"reason": reason} if reason else None,
        )

    async def rate(
        self, ticket: Ticket, actor_id: uuid.UUID, *, rating: int, comment: str | None
    ) -> None:
        if ticket.status not in _RATEABLE_STATUSES:
            raise ProblemException.unprocessable(
                detail="Rating is allowed only for resolved or closed tickets"
            )
        ticket.rating = rating
        ticket.rating_comment = comment
        await self._session.flush()
        await self._history.record(
            ticket.id,
            actor_id,
            TicketHistoryAction.RATED,
            to_value={"rating": rating, "comment": comment},
        )
        # Низкая оценка (1-2) → уведомление супервайзера/метрика — FR-8.2, E9 (#22).
