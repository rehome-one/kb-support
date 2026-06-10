"""Фиксация акта приёмки-передачи + резолв signing_status + OTP-resend (E10-9 PR-B #199; ADR-0016).

Оператор фиксирует `act_kind`/`acceptance_act_id` → сервер: (а) проставляет
`Ticket.acceptance_act_id` + `TicketCaseDetails.act_kind` (upsert деталей), (б) резолвит
`signing_status` через AcceptanceAct-клиент (config-gated; **upstream авторитетен, M4** —
None-резолв НЕ затирает поле), (в) триггерит OTP-resend через sms-seam (#161, инертно;
**OTP-код НИКОГДА не логируется/не хранится** — kb-support не генерит/не валидирует OTP),
(г) пишет строку аудита. Возвращает резолвнутый `AcceptanceAct` (или None) — для каскада PR-C.
"""

from __future__ import annotations

import uuid

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.acceptance_act import AcceptanceAct, AcceptanceActClient
from api.config import Settings
from api.notifications.channels import maybe_schedule_sms
from api.observability.logging import get_logger
from api.tickets.case_repository import TicketCaseDetailsRepository
from api.tickets.enums import ActKind, CaseType, SigningStatus
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository
from api.tickets.models import Ticket

_logger = get_logger("claims.acceptance")

_OTP_RESEND_SUMMARY = "Переотправка кода подписания акта"  # нейтрально, без ПДн/OTP


def _safe_signing_status(raw: str | None) -> SigningStatus | None:
    """Валидировать signing_status из upstream-резолва; неизвестное → None (не пишем мусор)."""
    if not raw:
        return None
    try:
        return SigningStatus(raw)
    except ValueError:
        _logger.warning("acceptance act unknown signing_status from upstream (ignored)")
        return None


async def record_acceptance_act(
    session: AsyncSession,
    ticket: Ticket,
    *,
    act_kind: ActKind,
    acceptance_act_id: uuid.UUID,
    client: AcceptanceActClient | None,
    background: BackgroundTasks,
    settings: Settings,
    actor_id: uuid.UUID,
) -> AcceptanceAct | None:
    """Зафиксировать акт, резолвить signing_status, OTP-resend. Commit — у вызывающего."""
    ticket.acceptance_act_id = acceptance_act_id

    repo = TicketCaseDetailsRepository(session)
    details = await repo.get_by_ticket(ticket.id)
    if details is None:
        details = await repo.create(ticket.id, CaseType.ACCEPTANCE_ACT, act_kind=act_kind)
    else:
        await repo.update_act(details, act_kind=act_kind)

    # Резолв signing_status (config-gated; upstream авторитетен, M4). None-резолв не затирает.
    act = await client.get_act(acceptance_act_id) if client is not None else None
    if act is not None:
        signing = _safe_signing_status(act.signing_status)
        if signing is not None:
            await repo.update_act(details, signing_status=signing)

    # OTP-resend seam (config-gated по sms_api_token, инертно до #161; OTP не логируется).
    maybe_schedule_sms(background, ticket, _OTP_RESEND_SUMMARY, settings)

    await TicketHistoryRepository(session).record(
        ticket.id,
        actor_id,
        TicketHistoryAction.ACCEPTANCE_ACT_RECORDED,
        to_value={"act_kind": act_kind.value, "signing_status": details.signing_status},
    )
    return act
