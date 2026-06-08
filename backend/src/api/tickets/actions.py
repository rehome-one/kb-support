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
from api.tickets.case_state_machine import is_allowed_case_transition
from api.tickets.enums import TicketCaseState, TicketStatus, TicketTeam
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository
from api.tickets.models import Ticket
from api.tickets.rating_metrics import record_rating
from api.tickets.repository import apply_status_side_effects
from api.tickets.state_machine import is_allowed_transition

# Оценка заявителя возможна только в терминальных состояниях.
_RATEABLE_STATUSES = frozenset({TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value})

# «4 глаза» (E10-2/E10-4 #192/#194, D6): первый подтверждающий выплату хранится в
# custom_fields.claims.payout_first_approver (реассайн словаря — JSONB не трекает in-place).
_CLAIMS_BLOCK = "claims"
_PAYOUT_APPROVER = "payout_first_approver"


def _claims_block(ticket: Ticket) -> dict[str, object]:
    cf = ticket.custom_fields or {}
    block = cf.get(_CLAIMS_BLOCK)
    return dict(block) if isinstance(block, dict) else {}


def _write_claims_block(ticket: Ticket, block: dict[str, object]) -> None:
    cf = dict(ticket.custom_fields or {})
    if block:
        cf[_CLAIMS_BLOCK] = block
    else:
        cf.pop(_CLAIMS_BLOCK, None)
    ticket.custom_fields = cf  # реассайн — иначе SQLAlchemy не увидит изменение JSONB


def _payout_first_approver(ticket: Ticket) -> str | None:
    value = _claims_block(ticket).get(_PAYOUT_APPROVER)
    return value if isinstance(value, str) else None


def _set_payout_first_approver(ticket: Ticket, actor_id: uuid.UUID) -> None:
    block = _claims_block(ticket)
    block[_PAYOUT_APPROVER] = str(actor_id)
    _write_claims_block(ticket, block)


def _clear_payout_first_approver(ticket: Ticket) -> None:
    block = _claims_block(ticket)
    if _PAYOUT_APPROVER in block:
        block.pop(_PAYOUT_APPROVER)
        _write_claims_block(ticket, block)


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
        # Распределение оценок (метрика, in-transaction как #168). Низкую оценку (1-2)
        # супервайзеру уведомляет роутер fire-after (#183, ADR-0012 D2/D4).
        record_rating(rating)

    async def transition_case_state(
        self,
        ticket: Ticket,
        actor_id: uuid.UUID,
        *,
        target: TicketCaseState,
        note: str | None = None,
    ) -> None:
        """Переход case_state разбирательства (§3.2.1, ADR-0013 D5). Запрещённый → 422.

        Не претензионная заявка (case_state=None) → 422. Идемпотентный no-op (cur==target) —
        без записи в журнал. PAYOUT_PENDING→PAID требует «4 глаза» (D6) — см. `_approve_payout`.
        """
        if ticket.case_state is None:
            raise ProblemException.unprocessable(
                detail="Ticket has no claim case state to transition"
            )
        current = TicketCaseState(ticket.case_state)
        if not is_allowed_case_transition(current, target):
            raise ProblemException.unprocessable(
                detail=f"Case state transition {current.value} → {target.value} is not allowed"
            )
        if current == target:
            return  # идемпотентный no-op — журнал не засоряем
        if current is TicketCaseState.PAYOUT_PENDING and target is TicketCaseState.PAID:
            await self._approve_payout(ticket, actor_id, note)
            return
        ticket.case_state = target.value
        await self._session.flush()
        to_value: dict[str, object] = {"case_state": target.value}
        if note:
            to_value["note"] = note
        await self._history.record(
            ticket.id,
            actor_id,
            TicketHistoryAction.CASE_STATE_CHANGED,
            from_value={"case_state": current.value},
            to_value=to_value,
        )

    async def _approve_payout(self, ticket: Ticket, actor_id: uuid.UUID, note: str | None) -> None:
        """«4 глаза» PAYOUT_PENDING→PAID (D6, FR-9.4): двое РАЗНЫХ сотрудников.

        Первый аппрув фиксирует actor_id (case_state остаётся PAYOUT_PENDING); второй
        (≠ первого) завершает переход в PAID. Тот же actor дважды → 409. Инвариант-гард
        (не отключается конфигом). Дубль-проверка на стороне releasePayout — seam E10-7.
        """
        first = _payout_first_approver(ticket)
        if first is None:
            _set_payout_first_approver(ticket, actor_id)
            await self._session.flush()
            await self._history.record(
                ticket.id,
                actor_id,
                TicketHistoryAction.PAYOUT_APPROVAL_RECORDED,
                to_value={"approver": str(actor_id)},
            )
            return
        if first == str(actor_id):
            raise ProblemException.conflict(
                detail="Second payout approval must be a different staff member"
            )
        _clear_payout_first_approver(ticket)
        ticket.case_state = TicketCaseState.PAID.value
        await self._session.flush()
        to_value: dict[str, object] = {
            "case_state": TicketCaseState.PAID.value,
            "approvers": [first, str(actor_id)],
        }
        if note:
            to_value["note"] = note
        await self._history.record(
            ticket.id,
            actor_id,
            TicketHistoryAction.CASE_STATE_CHANGED,
            from_value={"case_state": TicketCaseState.PAYOUT_PENDING.value},
            to_value=to_value,
        )
