"""Каскад ACCEPTANCE_ACT MOVE_OUT + ущерб → связанный COMPENSATION (E10-9 PR-C #199; ADR-0016 D3).

При резолве акта (PR-B) с `act_kind=MOVE_OUT` и `damage_amount>0` системно создаётся связанный
COMPENSATION-тикет (системный актор `CLAIMS_ACTOR_ID`). `claim_amount=damage_amount` — **как
ССЫЛКА/перенос из акта, без арифметики** (FR-9.8, деньги не считаем). Создание — через
`TicketRepository.create` (проходит `apply_claim_intake`: case_state, флаги D10, маршрутизация D8).
Линк **двусторонний в `case_details.payload`** (без миграции). **Идемпотентность (M1):** guard по
существующему линку родителя в той же транзакции → повторный резолв не двоит каскад.
"""

from __future__ import annotations

import decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import CLAIMS_ACTOR_ID
from api.clients.acceptance_act import AcceptanceAct
from api.observability.logging import get_logger
from api.tickets.case_repository import TicketCaseDetailsRepository
from api.tickets.enums import ActKind, CaseType, TicketChannel, TicketType
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketCreate

_logger = get_logger("claims.cascade")

_LINK_CHILD_KEY = "linked_compensation_ticket_id"  # на родителе (ACCEPTANCE_ACT)
_LINK_PARENT_KEY = "source_acceptance_ticket_id"  # на ребёнке (COMPENSATION)


async def maybe_cascade_compensation(
    session: AsyncSession, parent: Ticket, act: AcceptanceAct | None
) -> Ticket | None:
    """При MOVE_OUT+ущерб создать связанный COMPENSATION (идемпотентно). Commit — у вызывающего."""
    if act is None or act.kind != ActKind.MOVE_OUT.value:
        return None
    damage = act.damage_amount
    if damage is None or damage <= decimal.Decimal(0):
        return None

    repo = TicketCaseDetailsRepository(session)
    parent_details = await repo.get_by_ticket(parent.id)
    # Идемпотентность (M1): родитель уже сцеплен → no-op (guard в той же транзакции).
    if parent_details is not None and parent_details.payload.get(_LINK_CHILD_KEY):
        return None

    system = Principal(user_id=CLAIMS_ACTOR_ID, kind=PrincipalKind.OPERATOR, teams=frozenset())
    child = await TicketRepository(session).create(
        TicketCreate(
            subject=f"Ущерб при выезде по заявке {parent.number}",
            type=TicketType.COMPENSATION,
            channel=TicketChannel.SYSTEM,
            requester_id=parent.requester_id,
            # claim_amount как ССЫЛКА из акта (FR-9.8) — apply_claim_intake сохранит, не считая.
            custom_fields={"claim_amount": str(damage)},
        ),
        system,
    )

    # Двусторонний линк в case_details.payload (без миграции, ADR-0016 D3).
    child_details = await repo.get_by_ticket(child.id)
    if child_details is not None:
        await repo.update_payload(
            child_details, {**child_details.payload, _LINK_PARENT_KEY: str(parent.id)}
        )
    if parent_details is None:
        parent_details = await repo.create(parent.id, CaseType.ACCEPTANCE_ACT)
    await repo.update_payload(
        parent_details, {**parent_details.payload, _LINK_CHILD_KEY: str(child.id)}
    )

    await TicketHistoryRepository(session).record(
        parent.id,
        CLAIMS_ACTOR_ID,
        TicketHistoryAction.ACCEPTANCE_CASCADE_CREATED,
        to_value={"compensation_ticket_id": str(child.id)},
    )
    _logger.info("acceptance cascade created parent=%s child=%s", parent.number, child.number)
    return child
