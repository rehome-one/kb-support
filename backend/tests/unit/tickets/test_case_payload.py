"""Unit-тесты payload-валидатора claims + claims-enum + Numeric↔float (E10-1 #191)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from api.tickets.case_payload import validate_case_payload
from api.tickets.enums import (
    ActKind,
    CaseType,
    SigningStatus,
    TicketCaseState,
    TicketDecision,
)
from api.tickets.models import Ticket
from api.tickets.schemas import TicketRead


def test_enum_domains_match_contract() -> None:
    assert {e.value for e in TicketCaseState} == {
        "CLAIM_SUBMITTED",
        "DOCS_PENDING",
        "UNDER_REVIEW",
        "INSPECTION",
        "DECISION_MADE",
        "PAYOUT_PENDING",
        "PAID",
        "REJECTED",
    }
    assert {e.value for e in TicketDecision} == {"FULL", "PARTIAL", "REJECTED"}
    assert {e.value for e in ActKind} == {"MOVE_IN", "MOVE_OUT"}
    assert {e.value for e in SigningStatus} == {"one_signed", "both_signed", "disputed"}
    assert {e.value for e in CaseType} == {
        "COMPENSATION",
        "GUARANTEE",
        "INSURANCE",
        "ACCEPTANCE_ACT",
    }


def test_validate_compensation_known_fields() -> None:
    out = validate_case_payload(
        CaseType.COMPENSATION,
        {"limit_remaining": 30000.0, "late_submission": True, "evidence": ["f1", "f2"]},
    )
    assert out == {"limit_remaining": 30000.0, "late_submission": True, "evidence": ["f1", "f2"]}


def test_validate_allows_extra_fields() -> None:
    # Контракт payload = additionalProperties:true — неизвестные поля проходят (E10-5+ добор).
    out = validate_case_payload(CaseType.GUARANTEE, {"unknown_future_field": "x"})
    assert out["unknown_future_field"] == "x"


def test_validate_rejects_wrong_type_of_known_field() -> None:
    # Известное поле неверного типа → ошибка валидации.
    with pytest.raises(ValidationError):
        validate_case_payload(CaseType.COMPENSATION, {"late_submission": "not-a-bool-or-coercible"})


def test_validate_exclude_none() -> None:
    # Известные-незаданные поля не пишутся в JSONB (не раздуваем null-ключами).
    out = validate_case_payload(CaseType.INSURANCE, {"insurer_status": "received"})
    assert out == {"insurer_status": "received"}


def test_numeric_amount_round_trips_to_float_in_schema() -> None:
    # Cond-1: Numeric(14,2) в ORM → float в TicketRead без потери дробной части.
    import datetime as _dt
    import uuid as _uuid

    now = _dt.datetime(2026, 6, 8, tzinfo=_dt.UTC)
    ticket = Ticket(
        id=_uuid.uuid4(),
        number="RH-2001-00001",
        subject="seed",
        description="seed",
        status="OPEN",
        priority="normal",
        type="COMPENSATION",
        channel="LK_CLAIM",
        requester_id=_uuid.uuid4(),
        reopened_count=0,
        tags=[],
        custom_fields={},
        access_level="STAFF",
        claim_amount=Decimal("12345.67"),
        approved_amount=Decimal("10000.00"),
        created_at=now,
        updated_at=now,
    )
    read = TicketRead.model_validate(ticket)
    assert read.claim_amount == 12345.67
    assert read.approved_amount == 10000.0
    # И в JSON-сериализации (контрактный ответ) — число, не строка/Decimal.
    assert read.model_dump(mode="json")["claim_amount"] == 12345.67
