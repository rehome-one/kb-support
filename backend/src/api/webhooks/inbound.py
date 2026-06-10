"""Inbound webhook страховщика (E10-8 PR-C #198; ADR-0015 D1/D8, провизорный контракт).

`POST /api/v1/support/insurer-events` — m2m (kind=SERVICE, anti-spoofing) + верификация
входящей HMAC-подписи `X-Signature` по общему `insurer_inbound_secret` (config-gated,
fail-closed: пустой секрет → приём отклоняется, инертно до ops). Находит claims-заявку
INSURANCE по номеру (m2m-контекст, без visibility-filter — как from-email), проставляет
`insurance_event_id` + строку аудита → триггерит outbound `ticket.insurance_event` (D8).
Идемпотентность по `insurance_event_id`. Боевой контракт страховщика — при провижининге.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.errors import ProblemException
from api.tickets.enums import TicketType
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketEnvelope, TicketRead
from api.webhooks.dispatcher import schedule_webhook_event
from api.webhooks.enums import WebhookEvent
from api.webhooks.schemas import InsurerEventIngest
from api.webhooks.signing import verify_signature

router = APIRouter(prefix="/api/v1/support", tags=["Webhooks"])


def _resolve_request_id(raw: str | None) -> uuid.UUID:
    # Дубль admin-роутеров — будет вынесен в общий хелпер (#219).
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


def _envelope(ticket: Ticket, x_request_id: str | None) -> TicketEnvelope:
    return TicketEnvelope(
        data=TicketRead.model_validate(ticket), request_id=_resolve_request_id(x_request_id)
    )


@router.post(
    "/insurer-events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketEnvelope,
    summary="Приём webhook страховщика",
)
async def receive_insurer_event(
    request: Request,
    payload: InsurerEventIngest,
    background: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    # m2m-only: страховщик шлёт m2m; не-SERVICE → нельзя (anti-spoofing, ADR-0015 D8).
    if principal.kind is not PrincipalKind.SERVICE:
        raise ProblemException.forbidden(
            detail="Insurer event ingestion is a service-to-service operation"
        )
    settings = get_settings()
    secret = settings.insurer_inbound_secret
    raw = await request.body()  # точные байты, которые подписал страховщик
    signature = request.headers.get("X-Signature", "")
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    # Config-gate + anti-spoofing: пустой секрет (выключено) ИЛИ невалидная/просроченная
    # подпись → 403 (fail-closed). raw в лог/ошибку не попадает (ФЗ-152).
    if not secret or not verify_signature(
        payload=raw,
        secret=secret,
        header=signature,
        now=now,
        tolerance_seconds=settings.webhook_timestamp_tolerance_seconds,
    ):
        raise ProblemException.forbidden(detail="Invalid or missing webhook signature")

    ticket = await TicketRepository(session).find_active_by_number(payload.ticket_number)
    # 404 anti-enum: не наша заявка / не претензионная INSURANCE.
    if ticket is None or ticket.case_state is None or ticket.type != TicketType.INSURANCE.value:
        raise ProblemException.not_found(detail="Insurance claim ticket not found")

    # Идемпотентность по insurance_event_id: повтор той же доставки → no-op (без ретриггера).
    if ticket.insurance_event_id == payload.insurance_event_id:
        return _envelope(ticket, x_request_id)

    previous = ticket.insurance_event_id
    ticket.insurance_event_id = payload.insurance_event_id
    await TicketHistoryRepository(session).record(
        ticket.id,
        principal.user_id,
        TicketHistoryAction.INSURANCE_EVENT_RECEIVED,
        from_value={"insurance_event_id": str(previous) if previous else None},
        to_value={"insurance_event_id": str(payload.insurance_event_id)},
    )
    await session.commit()
    await session.refresh(ticket)
    # Триггер outbound ticket.insurance_event (D8) — fire-after подписчикам.
    await schedule_webhook_event(
        background, session, ticket, WebhookEvent.INSURANCE_EVENT, settings
    )
    return _envelope(ticket, x_request_id)
