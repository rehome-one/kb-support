"""Репозиторий деталей претензионного обращения (E10-1 #191, §3.11).

`TicketCaseDetails` 1:1 к Ticket. payload валидируется `validate_case_payload` по case_type
ДО записи. Commit — на стороне вызывающего (паттерн `TicketRepository`/`SLAPolicyRepository`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.tickets.case_payload import validate_case_payload
from api.tickets.enums import ActKind, CaseType, SigningStatus
from api.tickets.models import TicketCaseDetails


class TicketCaseDetailsRepository:
    """Чтение/запись деталей претензии поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_ticket(self, ticket_id: uuid.UUID) -> TicketCaseDetails | None:
        stmt = select(TicketCaseDetails).where(TicketCaseDetails.ticket_id == ticket_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        ticket_id: uuid.UUID,
        case_type: CaseType,
        *,
        payload: dict[str, object] | None = None,
        act_kind: ActKind | None = None,
        signing_status: SigningStatus | None = None,
    ) -> TicketCaseDetails:
        """Создать детали (payload валидируется по case_type). Один на заявку (uniq ticket_id)."""
        details = TicketCaseDetails(
            ticket_id=ticket_id,
            case_type=case_type.value,
            act_kind=act_kind.value if act_kind else None,
            signing_status=signing_status.value if signing_status else None,
            payload=validate_case_payload(case_type, dict(payload or {})),
        )
        self._session.add(details)
        await self._session.flush()
        return details

    async def update_payload(
        self, details: TicketCaseDetails, payload: dict[str, object]
    ) -> TicketCaseDetails:
        """Перезаписать payload (валидируется по текущему case_type). Реассайн — JSONB."""
        details.payload = validate_case_payload(CaseType(details.case_type), dict(payload))
        await self._session.flush()
        return details

    async def update_act(
        self,
        details: TicketCaseDetails,
        *,
        act_kind: ActKind | None = None,
        signing_status: SigningStatus | None = None,
    ) -> TicketCaseDetails:
        """Обновить typed-поля акта (E10-9). Передан None → поле не трогаем (M4: upstream-резолв
        авторитетен, но отсутствие резолва НЕ затирает signing_status в NULL)."""
        if act_kind is not None:
            details.act_kind = act_kind.value
        if signing_status is not None:
            details.signing_status = signing_status.value
        await self._session.flush()
        return details
