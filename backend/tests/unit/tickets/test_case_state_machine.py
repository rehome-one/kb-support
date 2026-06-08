"""Unit-тесты машины case_state (E10-2 #192, §3.2.1, ADR-0013 D5)."""

from __future__ import annotations

from api.tickets.case_state_machine import (
    CASE_TERMINAL_STATES,
    is_allowed_case_transition,
    is_case_terminal,
)
from api.tickets.enums import TicketCaseState as S


def test_linear_chain_allowed() -> None:
    assert is_allowed_case_transition(S.CLAIM_SUBMITTED, S.DOCS_PENDING)
    assert is_allowed_case_transition(S.DOCS_PENDING, S.UNDER_REVIEW)
    assert is_allowed_case_transition(S.UNDER_REVIEW, S.INSPECTION)
    assert is_allowed_case_transition(S.INSPECTION, S.DECISION_MADE)
    assert is_allowed_case_transition(S.DECISION_MADE, S.PAYOUT_PENDING)
    assert is_allowed_case_transition(S.PAYOUT_PENDING, S.PAID)


def test_inspection_optional() -> None:
    # UNDER_REVIEW можно сразу в DECISION_MADE (минуя INSPECTION).
    assert is_allowed_case_transition(S.UNDER_REVIEW, S.DECISION_MADE)


def test_rejected_reachable_from_intermediate() -> None:
    for state in (
        S.CLAIM_SUBMITTED,
        S.DOCS_PENDING,
        S.UNDER_REVIEW,
        S.INSPECTION,
        S.DECISION_MADE,
        S.PAYOUT_PENDING,
    ):
        assert is_allowed_case_transition(state, S.REJECTED), state


def test_forbidden_skips() -> None:
    assert not is_allowed_case_transition(S.CLAIM_SUBMITTED, S.PAID)
    assert not is_allowed_case_transition(S.CLAIM_SUBMITTED, S.PAYOUT_PENDING)
    assert not is_allowed_case_transition(S.UNDER_REVIEW, S.PAYOUT_PENDING)
    # Обратных переходов нет.
    assert not is_allowed_case_transition(S.UNDER_REVIEW, S.DOCS_PENDING)
    assert not is_allowed_case_transition(S.DECISION_MADE, S.UNDER_REVIEW)


def test_terminals_have_no_exits() -> None:
    assert {S.PAID, S.REJECTED} == CASE_TERMINAL_STATES
    for terminal in (S.PAID, S.REJECTED):
        assert is_case_terminal(terminal)
        for target in S:
            if target is terminal:
                continue
            assert not is_allowed_case_transition(terminal, target), (terminal, target)


def test_idempotent_no_op_allowed() -> None:
    assert is_allowed_case_transition(S.UNDER_REVIEW, S.UNDER_REVIEW)
    assert is_allowed_case_transition(S.PAID, S.PAID)
