"""Unit-тесты машины состояний статусов (без БД)."""

from __future__ import annotations

import itertools

import pytest

from api.tickets.enums import TicketStatus
from api.tickets.state_machine import ALLOWED_TRANSITIONS, is_allowed_transition


def test_table_keys_and_values_are_valid_statuses() -> None:
    for source, targets in ALLOWED_TRANSITIONS.items():
        assert isinstance(source, TicketStatus)
        for target in targets:
            assert isinstance(target, TicketStatus)
            assert target != source  # no-op в таблице не хранится


def test_no_op_transition_is_allowed() -> None:
    for status in TicketStatus:
        assert is_allowed_transition(status, status) is True


@pytest.mark.parametrize(("source", "targets"), list(ALLOWED_TRANSITIONS.items()))
def test_allowed_transitions_return_true(
    source: TicketStatus, targets: frozenset[TicketStatus]
) -> None:
    for target in targets:
        assert is_allowed_transition(source, target) is True


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (TicketStatus.NEW, TicketStatus.RESOLVED),
        (TicketStatus.OPEN, TicketStatus.CLOSED),
        (TicketStatus.CLOSED, TicketStatus.OPEN),
        (TicketStatus.RESOLVED, TicketStatus.OPEN),
        (TicketStatus.NEW, TicketStatus.REOPENED),
    ],
)
def test_representative_forbidden_transitions_return_false(
    source: TicketStatus, target: TicketStatus
) -> None:
    assert is_allowed_transition(source, target) is False


def test_every_pair_consistent_with_table() -> None:
    for source, target in itertools.product(TicketStatus, repeat=2):
        expected = source == target or target in ALLOWED_TRANSITIONS.get(source, frozenset())
        assert is_allowed_transition(source, target) is expected
