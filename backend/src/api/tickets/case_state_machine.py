"""Машина состояний разбирательства претензии `case_state` (E10-2 #192, §3.2.1, ADR-0013 D5).

ТЗ §3.2.1 задаёт линейную цепочку; таблица ниже — проектное расширение D5 (REJECTED из
промежуточных стадий, опциональный INSPECTION, терминалы PAID/REJECTED). Запрещённый переход
отклоняется вызывающим с 422 (как `state_machine.py` для status, но там 409 — здесь §3.2.1/
контракт требуют 422). Каждый фактический переход фиксируется в TicketHistory (§3.7).

Эталон — `state_machine.py` (таблица + is_allowed + terminal).
"""

from __future__ import annotations

from api.tickets.enums import TicketCaseState

# Из какого состояния в какие разрешён переход (ADR-0013 D5).
CASE_ALLOWED_TRANSITIONS: dict[TicketCaseState, frozenset[TicketCaseState]] = {
    TicketCaseState.CLAIM_SUBMITTED: frozenset(
        {TicketCaseState.DOCS_PENDING, TicketCaseState.UNDER_REVIEW, TicketCaseState.REJECTED}
    ),
    TicketCaseState.DOCS_PENDING: frozenset(
        {TicketCaseState.UNDER_REVIEW, TicketCaseState.REJECTED}
    ),
    TicketCaseState.UNDER_REVIEW: frozenset(
        {
            TicketCaseState.INSPECTION,
            TicketCaseState.DECISION_MADE,
            TicketCaseState.REJECTED,
        }
    ),
    TicketCaseState.INSPECTION: frozenset(
        {TicketCaseState.DECISION_MADE, TicketCaseState.REJECTED}
    ),
    TicketCaseState.DECISION_MADE: frozenset(
        {TicketCaseState.PAYOUT_PENDING, TicketCaseState.REJECTED}
    ),
    TicketCaseState.PAYOUT_PENDING: frozenset({TicketCaseState.PAID, TicketCaseState.REJECTED}),
    TicketCaseState.PAID: frozenset(),
    TicketCaseState.REJECTED: frozenset(),
}


def is_allowed_case_transition(current: TicketCaseState, target: TicketCaseState) -> bool:
    """Разрешён ли переход current→target. Идемпотентный no-op (cur==target) — да."""
    if current == target:
        return True
    return target in CASE_ALLOWED_TRANSITIONS.get(current, frozenset())


# Терминальные состояния разбирательства (из них переходов нет).
CASE_TERMINAL_STATES: frozenset[TicketCaseState] = frozenset(
    {TicketCaseState.PAID, TicketCaseState.REJECTED}
)


def is_case_terminal(state: TicketCaseState) -> bool:
    return state in CASE_TERMINAL_STATES
