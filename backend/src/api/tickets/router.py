"""Эндпоинты ядра заявок: создание (POST) и карточка (GET) — E1, #6.

Контракт: `POST /api/v1/support/tickets` (201), `GET /api/v1/support/tickets/{id}`
(200 / 404). Аутентификация — `get_current_principal` (seam, #29). Доступ к
карточке — storage-level фильтр (NFR-1.2): чужая/несуществующая заявка → 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.db import get_session
from api.errors import ProblemException
from api.tickets.history import TicketHistoryRepository
from api.tickets.repository import TicketRepository
from api.tickets.schemas import (
    TicketCreate,
    TicketEnvelope,
    TicketHistoryListEnvelope,
    TicketHistoryRead,
    TicketRead,
)

router = APIRouter(prefix="/api/v1/support/tickets", tags=["Tickets"])


def _resolve_request_id(raw: str | None) -> uuid.UUID:
    """Взять request_id из заголовка `X-Request-Id` или сгенерировать новый."""
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketEnvelope,
    summary="Создать заявку",
)
async def create_ticket(
    payload: TicketCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).create(payload, principal)
    await session.commit()
    await session.refresh(ticket)
    return TicketEnvelope(
        data=TicketRead.model_validate(ticket),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/{ticket_id}",
    response_model=TicketEnvelope,
    summary="Карточка заявки",
)
async def get_ticket(
    ticket_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    return TicketEnvelope(
        data=TicketRead.model_validate(ticket),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/{ticket_id}/history",
    response_model=TicketHistoryListEnvelope,
    summary="Журнал действий по заявке (внутренний)",
)
async def get_ticket_history(
    ticket_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketHistoryListEnvelope:
    # Сначала видимость самой заявки (404 для чужой/несуществующей —
    # anti-enumeration), затем — журнал только операторам (внутренние данные §3.7).
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    if not principal.is_operator:
        raise ProblemException.forbidden(detail="Ticket history is available to operators only")
    rows = await TicketHistoryRepository(session).list_for_ticket(ticket_id)
    return TicketHistoryListEnvelope(
        data=[TicketHistoryRead.model_validate(row) for row in rows],
        request_id=_resolve_request_id(x_request_id),
    )
