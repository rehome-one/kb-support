"""Inbound сигнал платёжного контура о гарантийном исключении (E10-10 PR-A #200; ADR-0017 D1).

`POST /api/v1/support/guarantee-events` — m2m (kind=SERVICE, anti-spoofing) + верификация HMAC
по `guarantee_inbound_secret` (config-gated, fail-closed). При исключении (5.7.6/7/8) **системно
создаёт GUARANTEE-тикет** (актор `CLAIMS_ACTOR_ID`, channel=SYSTEM → finance по D8). Регресс-поля —
ССЫЛКИ (деньги/пеню НЕ считаем, D2): `regress_obligation_id` (плоская колонка), `missed_payment_id`/
`late_fee_accrued`/`guarantee_paused` (GuaranteePayload). **Идемпотентность по `reference`** в
`custom_fields.guarantee_reference` (uniq-индекс = hardening-follow-up, ADR-0017 A1).
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import CLAIMS_ACTOR_ID
from api.config import get_settings
from api.db import get_session
from api.errors import ProblemException
from api.tickets.case_repository import TicketCaseDetailsRepository
from api.tickets.enums import TicketChannel, TicketType
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketCreate, TicketEnvelope, TicketRead
from api.webhooks.schemas import GuaranteeEventIngest
from api.webhooks.signing import verify_signature

router = APIRouter(prefix="/api/v1/support", tags=["Webhooks"])

_GUARANTEE_SUSPENDED = "guarantee_suspended"  # exception_kind, при котором гарантия приостановлена


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
    "/guarantee-events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketEnvelope,
    summary="Приём сигнала гарантийного исключения",
)
async def receive_guarantee_event(
    request: Request,
    payload: GuaranteeEventIngest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    # m2m-only: сигнал от платёжного контура; не-SERVICE → нельзя (anti-spoofing, ADR-0017 D1).
    if principal.kind is not PrincipalKind.SERVICE:
        raise ProblemException.forbidden(
            detail="Guarantee event ingestion is a service-to-service operation"
        )
    settings = get_settings()
    secret = settings.guarantee_inbound_secret
    raw = await request.body()
    signature = request.headers.get("X-Signature", "")
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    # Config-gate + anti-spoofing: пустой секрет ИЛИ невалидная подпись → 403 (fail-closed).
    if not secret or not verify_signature(
        payload=raw,
        secret=secret,
        header=signature,
        now=now,
        tolerance_seconds=settings.webhook_timestamp_tolerance_seconds,
    ):
        raise ProblemException.forbidden(detail="Invalid or missing webhook signature")

    repo = TicketRepository(session)
    # Идемпотентность (A1): повтор сигнала с тем же reference → no-op (возврат существующей).
    existing = await repo.find_guarantee_by_reference(payload.reference)
    if existing is not None:
        return _envelope(existing, x_request_id)

    # Системное создание GUARANTEE (актор kind=OPERATOR, чтобы requester_id из payload принялся).
    system = Principal(user_id=CLAIMS_ACTOR_ID, kind=PrincipalKind.OPERATOR, teams=frozenset())
    ticket = await repo.create(
        TicketCreate(
            subject=f"Гарантийное исключение: {payload.exception_kind}",
            type=TicketType.GUARANTEE,
            channel=TicketChannel.SYSTEM,
            requester_id=payload.requester_id,
            custom_fields={
                "guarantee_reference": payload.reference,
                "exception_kind": payload.exception_kind,
            },
        ),
        system,
    )

    # Регресс-ССЫЛКИ (D2, деньги не считаем): плоская колонка + поля GuaranteePayload.
    if payload.regress_obligation_id is not None:
        ticket.regress_obligation_id = payload.regress_obligation_id
    details = await TicketCaseDetailsRepository(session).get_by_ticket(ticket.id)
    if details is not None:
        gp = dict(details.payload)
        if payload.missed_payment_id is not None:
            gp["missed_payment_id"] = str(payload.missed_payment_id)
        if payload.late_fee_accrued is not None:
            gp["late_fee_accrued"] = payload.late_fee_accrued  # ссылка, приходит готовой
        if payload.exception_kind == _GUARANTEE_SUSPENDED:
            gp["guarantee_paused"] = True
        await TicketCaseDetailsRepository(session).update_payload(details, gp)
    await session.flush()

    await TicketHistoryRepository(session).record(
        ticket.id,
        CLAIMS_ACTOR_ID,
        TicketHistoryAction.GUARANTEE_EVENT_RECEIVED,
        to_value={"exception_kind": payload.exception_kind},
    )
    await session.commit()
    await session.refresh(ticket)
    return _envelope(ticket, x_request_id)
