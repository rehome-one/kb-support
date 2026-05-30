"""Доступ к данным заявок. Контроль доступа — на уровне SQL-запроса (NFR-1.2)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.tickets.access import visibility_filter
from api.tickets.enums import AccessLevel, TicketChannel, TicketPriority, TicketStatus
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository, record_changes
from api.tickets.models import Ticket
from api.tickets.numbering import generate_ticket_number
from api.tickets.schemas import TicketCreate, TicketUpdate

# Поля, изменения которых пишутся в журнал §3.7 (см. _FIELD_ACTIONS).
_AUDITED_FIELDS = ("status", "priority", "type", "team", "tags")


class TicketRepository:
    """Репозиторий заявок поверх `AsyncSession` (commit — на стороне вызывающего)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._history = TicketHistoryRepository(session)

    async def create(self, payload: TicketCreate, principal: Principal) -> Ticket:
        """Создать заявку.

        `requester_id`: оператор может создать от имени заявителя (из payload);
        заявитель — только от своего имени (из принципала, payload игнорируется).
        """
        requester_id = principal.user_id
        if principal.is_operator and payload.requester_id is not None:
            requester_id = payload.requester_id

        ticket = Ticket(
            number=await generate_ticket_number(self._session),
            subject=payload.subject,
            description=payload.description or "",
            type=payload.type.value,
            status=TicketStatus.NEW.value,
            priority=(payload.priority or TicketPriority.NORMAL).value,
            channel=(payload.channel or TicketChannel.WEB_FORM).value,
            access_level=AccessLevel.LOGGED.value,
            requester_id=requester_id,
            premises_id=payload.premises_id,
            booking_id=payload.booking_id,
            tags=payload.tags or [],
            custom_fields=payload.custom_fields or {},
        )
        self._session.add(ticket)
        await self._session.flush()
        # ФЗ-152 / §3.7: первая запись журнала — создание. actor = принципал
        # (для оператора-от-имени-заявителя actor — оператор, requester_id — заявитель).
        await self._history.record(
            ticket.id,
            principal.user_id,
            TicketHistoryAction.CREATED,
            to_value={"status": ticket.status},
        )
        return ticket

    async def get_for_principal(self, ticket_id: uuid.UUID, principal: Principal) -> Ticket | None:
        """Вернуть заявку, если она видима субъекту, иначе None (→ 404)."""
        stmt = select(Ticket).where(Ticket.id == ticket_id, visibility_filter(principal))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def apply_update(
        self, ticket: Ticket, payload: TicketUpdate, principal: Principal
    ) -> Ticket:
        """Применить частичное обновление, lifecycle-эффекты и запись в журнал.

        Валидация перехода статуса и RBAC выполняются вызывающим (router) ДО
        вызова. Здесь — только мутация + аудит изменений отслеживаемых полей.
        """
        fields_set = payload.model_fields_set
        before: dict[str, Any] = {field: getattr(ticket, field) for field in _AUDITED_FIELDS}
        old_status = ticket.status

        if "subject" in fields_set and payload.subject is not None:
            ticket.subject = payload.subject
        if "status" in fields_set and payload.status is not None:
            ticket.status = payload.status.value
        if "priority" in fields_set and payload.priority is not None:
            ticket.priority = payload.priority.value
        if "type" in fields_set and payload.type is not None:
            ticket.type = payload.type.value
        if "team" in fields_set and payload.team is not None:
            ticket.team = payload.team.value
        if "tags" in fields_set and payload.tags is not None:
            ticket.tags = payload.tags
        if "custom_fields" in fields_set and payload.custom_fields is not None:
            ticket.custom_fields = payload.custom_fields

        self._apply_status_side_effects(ticket, old_status)
        await self._session.flush()

        after: dict[str, Any] = {field: getattr(ticket, field) for field in _AUDITED_FIELDS}
        await record_changes(self._history, ticket.id, principal.user_id, before, after)
        return ticket

    @staticmethod
    def _apply_status_side_effects(ticket: Ticket, old_status: str) -> None:
        """Lifecycle-эффекты смены статуса (ТЗ §3.1): счётчик переоткрытий и метки."""
        if ticket.status == old_status:
            return
        now = datetime.datetime.now(datetime.UTC)
        if ticket.status == TicketStatus.REOPENED.value:
            ticket.reopened_count += 1
        elif ticket.status == TicketStatus.RESOLVED.value:
            ticket.resolved_at = now
        elif ticket.status == TicketStatus.CLOSED.value:
            ticket.closed_at = now
