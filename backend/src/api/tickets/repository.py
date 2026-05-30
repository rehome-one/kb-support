"""Доступ к данным заявок. Контроль доступа — на уровне SQL-запроса (NFR-1.2)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.tickets.access import visibility_filter
from api.tickets.enums import AccessLevel, TicketChannel, TicketPriority, TicketStatus
from api.tickets.models import Ticket
from api.tickets.numbering import generate_ticket_number
from api.tickets.schemas import TicketCreate


class TicketRepository:
    """Репозиторий заявок поверх `AsyncSession` (commit — на стороне вызывающего)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        return ticket

    async def get_for_principal(self, ticket_id: uuid.UUID, principal: Principal) -> Ticket | None:
        """Вернуть заявку, если она видима субъекту, иначе None (→ 404)."""
        stmt = select(Ticket).where(Ticket.id == ticket_id, visibility_filter(principal))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
