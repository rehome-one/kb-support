"""Доступ к данным заявок. Контроль доступа — на уровне SQL-запроса (NFR-1.2)."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, and_, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.tickets.access import visibility_filter
from api.tickets.enums import AccessLevel, TicketChannel, TicketPriority, TicketStatus
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository, record_changes
from api.tickets.models import Ticket
from api.tickets.numbering import generate_ticket_number
from api.tickets.pagination import (
    SortSpec,
    decode_cursor,
    encode_cursor,
    get_sort_spec,
    keyset_predicate,
    order_by_clause,
    row_cursor_value,
)
from api.tickets.schemas import TicketCreate, TicketUpdate


@dataclass(frozen=True)
class TicketFilters:
    """Фильтры списка заявок (значения enum — уже строки)."""

    status: str | None = None
    type: str | None = None
    priority: str | None = None
    channel: str | None = None
    team: str | None = None
    assignee_id: uuid.UUID | None = None
    requester_id: uuid.UUID | None = None
    premises_id: uuid.UUID | None = None
    tag: str | None = None
    sla_breached: bool | None = None


# Поля, изменения которых пишутся в журнал §3.7 (см. _FIELD_ACTIONS).
_AUDITED_FIELDS = ("status", "priority", "type", "team", "tags")


def apply_status_side_effects(ticket: Ticket, old_status: str) -> None:
    """Lifecycle-эффекты смены статуса (ТЗ §3.1): счётчик переоткрытий и метки.

    Общий хелпер для PATCH (#8) и action-эндпоинтов (#12).
    """
    if ticket.status == old_status:
        return
    now = datetime.datetime.now(datetime.UTC)
    if ticket.status == TicketStatus.REOPENED.value:
        ticket.reopened_count += 1
    elif ticket.status == TicketStatus.RESOLVED.value:
        ticket.resolved_at = now
    elif ticket.status == TicketStatus.CLOSED.value:
        ticket.closed_at = now


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

    def _list_conditions(
        self, principal: Principal, filters: TicketFilters
    ) -> list[ColumnElement[bool]]:
        """Видимость (NFR-1.2) + фильтры — всё в SQL."""
        conditions: list[ColumnElement[bool]] = [visibility_filter(principal)]
        if filters.status is not None:
            conditions.append(Ticket.status == filters.status)
        if filters.type is not None:
            conditions.append(Ticket.type == filters.type)
        if filters.priority is not None:
            conditions.append(Ticket.priority == filters.priority)
        if filters.channel is not None:
            conditions.append(Ticket.channel == filters.channel)
        if filters.team is not None:
            conditions.append(Ticket.team == filters.team)
        if filters.assignee_id is not None:
            conditions.append(Ticket.assignee_id == filters.assignee_id)
        if filters.requester_id is not None:
            conditions.append(Ticket.requester_id == filters.requester_id)
        if filters.premises_id is not None:
            conditions.append(Ticket.premises_id == filters.premises_id)
        if filters.tag is not None:
            # tag = ANY(tags) — заявка содержит указанный тег.
            conditions.append(Ticket.tags.any(literal(filters.tag)))
        if filters.sla_breached is not None:
            now = datetime.datetime.now(datetime.UTC)
            if filters.sla_breached:
                conditions.append(
                    and_(Ticket.resolution_due_at.is_not(None), Ticket.resolution_due_at < now)
                )
            else:
                conditions.append(
                    or_(Ticket.resolution_due_at.is_(None), Ticket.resolution_due_at >= now)
                )
        return conditions

    async def list_tickets(
        self,
        principal: Principal,
        *,
        filters: TicketFilters,
        sort: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[Ticket], str | None, bool]:
        """Список видимых заявок с фильтрами, сортировкой и keyset-пагинацией.

        Возвращает (строки, next_cursor, has_more). Невалидный cursor → ValueError.
        """
        spec: SortSpec = get_sort_spec(sort)
        conditions = self._list_conditions(principal, filters)
        if cursor is not None:
            value, cursor_id = decode_cursor(cursor)
            conditions.append(keyset_predicate(spec, value, cursor_id))
        stmt = (
            select(Ticket)
            .where(and_(*conditions))
            .order_by(*order_by_clause(spec))
            .limit(limit + 1)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            encode_cursor(row_cursor_value(rows[-1], spec), rows[-1].id)
            if has_more and rows
            else None
        )
        return rows, next_cursor, has_more

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

        apply_status_side_effects(ticket, old_status)
        await self._session.flush()

        after: dict[str, Any] = {field: getattr(ticket, field) for field in _AUDITED_FIELDS}
        await record_changes(self._history, ticket.id, principal.user_id, before, after)
        return ticket
