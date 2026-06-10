"""Unit-тесты Pydantic-схем тикетов (без БД)."""

from __future__ import annotations

import datetime
import types
import uuid

import pytest
from pydantic import ValidationError

from api.tickets.enums import (
    TicketCaseState,
    TicketPriority,
    TicketStatus,
    TicketType,
)
from api.tickets.schemas import TicketCreate, TicketRead


def test_create_minimal_valid() -> None:
    tc = TicketCreate(subject="Нужна помощь", type=TicketType.PAYMENT)
    assert tc.type is TicketType.PAYMENT
    assert tc.priority is None
    assert tc.requester_id is None


def test_create_coerces_enum_from_string() -> None:
    tc = TicketCreate.model_validate({"subject": "x", "type": "MAINTENANCE"})
    assert tc.type is TicketType.MAINTENANCE


def test_create_requires_subject() -> None:
    with pytest.raises(ValidationError):
        TicketCreate.model_validate({"type": "PAYMENT"})


def test_create_requires_type() -> None:
    with pytest.raises(ValidationError):
        TicketCreate.model_validate({"subject": "x"})


def test_create_rejects_empty_subject() -> None:
    with pytest.raises(ValidationError):
        TicketCreate.model_validate({"subject": "", "type": "PAYMENT"})


def test_create_rejects_too_long_subject() -> None:
    with pytest.raises(ValidationError):
        TicketCreate.model_validate({"subject": "x" * 301, "type": "PAYMENT"})


def test_create_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TicketCreate.model_validate({"subject": "x", "type": "PAYMENT", "status": "OPEN"})


def test_create_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        TicketCreate.model_validate({"subject": "x", "type": "NOPE"})


def _ticket_like() -> types.SimpleNamespace:
    now = datetime.datetime(2026, 5, 30, tzinfo=datetime.UTC)
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        number="RH-2026-00001",
        subject="s",
        description="d",
        status="NEW",
        priority="normal",
        type="PAYMENT",
        channel="WEB_FORM",
        requester_id=uuid.uuid4(),
        assignee_id=None,
        team=None,
        premises_id=None,
        booking_id=None,
        collaborator_id=None,
        service_order_id=None,
        chat_session_id=None,
        sla_policy_id=None,
        first_response_due_at=None,
        resolution_due_at=None,
        first_responded_at=None,
        resolved_at=None,
        closed_at=None,
        reopened_count=0,
        tags=[],
        custom_fields={},
        access_level="LOGGED",
        rating=None,
        rating_comment=None,
        created_at=now,
        updated_at=now,
    )


def test_read_serializes_base_fields() -> None:
    read = TicketRead.model_validate(_ticket_like())
    assert read.status is TicketStatus.NEW
    assert read.priority is TicketPriority.NORMAL
    assert read.number == "RH-2026-00001"


def test_read_claims_fields_null_on_e1() -> None:
    """Поля §3.1.1 присутствуют для контракта, но всегда null на E1."""
    dumped = TicketRead.model_validate(_ticket_like()).model_dump(mode="json")
    for field_name in (
        "case_state",
        "claim_amount",
        "approved_amount",
        "decision",
        "decision_reason",
        "linked_payment_id",
        "case_details",
    ):
        assert dumped[field_name] is None


def _read_with_case_state(case_state: str | None) -> TicketRead:
    raw = _ticket_like()
    raw.case_state = case_state
    return TicketRead.model_validate(raw)


def test_allowed_case_transitions_empty_for_non_claims() -> None:
    """Не-claims заявка (case_state=None) → пустой список переходов разбирательства (#231)."""
    assert _read_with_case_state(None).allowed_case_transitions == []


def test_allowed_case_transitions_from_start() -> None:
    """CLAIM_SUBMITTED → DOCS_PENDING / UNDER_REVIEW / REJECTED (порядок = объявление enum)."""
    assert _read_with_case_state("CLAIM_SUBMITTED").allowed_case_transitions == [
        TicketCaseState.DOCS_PENDING,
        TicketCaseState.UNDER_REVIEW,
        TicketCaseState.REJECTED,
    ]


def test_allowed_case_transitions_mid_state() -> None:
    """UNDER_REVIEW → INSPECTION / DECISION_MADE / REJECTED; текущее состояние не входит."""
    assert _read_with_case_state("UNDER_REVIEW").allowed_case_transitions == [
        TicketCaseState.INSPECTION,
        TicketCaseState.DECISION_MADE,
        TicketCaseState.REJECTED,
    ]


@pytest.mark.parametrize("terminal", ["PAID", "REJECTED"])
def test_allowed_case_transitions_empty_for_terminal(terminal: str) -> None:
    """Терминальные состояния (PAID/REJECTED) не имеют исходящих переходов."""
    assert _read_with_case_state(terminal).allowed_case_transitions == []


def test_allowed_case_transitions_empty_for_unknown_value() -> None:
    """Значение вне домена не роняет computed-поле — защитный guard возвращает []."""
    assert _read_with_case_state("NOPE").allowed_case_transitions == []
