"""Unit-тесты fire-after передачи события страховщику (E10-10 PR-B #200; ADR-0017 D3)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import BackgroundTasks

from api.config import get_settings
from api.tickets import insurer_dispatch as dispatch_module
from api.tickets.enums import TicketCaseState, TicketType
from api.tickets.insurer_dispatch import (
    dispatch_insurer_event,
    is_insurance_submitted,
    maybe_schedule_insurer_event,
)
from api.tickets.models import Ticket


def _ticket(ttype: str, case_state: str | None) -> Ticket:
    return Ticket(
        id=uuid.uuid4(),
        number="RH-2026-00100",
        type=ttype,
        case_state=case_state,
        insurance_event_id=uuid.uuid4(),
    )


def test_predicate_true_on_insurance_entering_under_review() -> None:
    t = _ticket(TicketType.INSURANCE.value, TicketCaseState.UNDER_REVIEW.value)
    assert is_insurance_submitted(t, TicketCaseState.DOCS_PENDING.value) is True


def test_predicate_false_when_already_under_review() -> None:
    t = _ticket(TicketType.INSURANCE.value, TicketCaseState.UNDER_REVIEW.value)
    assert is_insurance_submitted(t, TicketCaseState.UNDER_REVIEW.value) is False


def test_predicate_false_for_non_insurance() -> None:
    t = _ticket(TicketType.COMPENSATION.value, TicketCaseState.UNDER_REVIEW.value)
    assert is_insurance_submitted(t, TicketCaseState.DOCS_PENDING.value) is False


def test_predicate_false_for_other_state() -> None:
    t = _ticket(TicketType.INSURANCE.value, TicketCaseState.DECISION_MADE.value)
    assert is_insurance_submitted(t, TicketCaseState.UNDER_REVIEW.value) is False


def test_gate_off_when_token_empty() -> None:
    settings = get_settings().model_copy(update={"insurer_api_token": ""})
    background = BackgroundTasks()
    t = _ticket(TicketType.INSURANCE.value, TicketCaseState.UNDER_REVIEW.value)
    assert maybe_schedule_insurer_event(background, t, "DOCS_PENDING", settings) is False
    assert list(background.tasks) == []


def test_scheduled_when_on_and_submitted() -> None:
    settings = get_settings().model_copy(update={"insurer_api_token": "tok"})
    background = BackgroundTasks()
    t = _ticket(TicketType.INSURANCE.value, TicketCaseState.UNDER_REVIEW.value)
    assert maybe_schedule_insurer_event(background, t, "DOCS_PENDING", settings) is True
    assert len(background.tasks) == 1
    assert background.tasks[0].func is dispatch_insurer_event


@pytest.mark.asyncio
async def test_dispatch_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: object, **k: object) -> object:
        raise RuntimeError("down")

    monkeypatch.setattr(dispatch_module, "build_resilient_client", _boom)
    from api.clients.insurer import InsurerEvent

    await dispatch_insurer_event(
        InsurerEvent(ticket_id=uuid.uuid4(), insurance_event_id=None), get_settings()
    )  # не бросает
