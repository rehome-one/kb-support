"""Unit-тесты whitelist-конверта webhook-событий (E10-8 PR-B #198; ADR-0015 D5/D7)."""

from __future__ import annotations

import datetime
import decimal
import json
import uuid

from api.tickets.models import Ticket
from api.webhooks.enums import WebhookEvent
from api.webhooks.events import build_delivery

_NOW = datetime.datetime(2026, 6, 10, 12, 0, 0, tzinfo=datetime.UTC)


def _ticket(**kwargs: object) -> Ticket:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "number": "RH-2026-00001",
        "decision": None,
        "approved_amount": None,
        "case_state": None,
        "linked_payment_id": None,
    }
    base.update(kwargs)
    return Ticket(**base)


def test_case_decided_envelope_whitelist_and_amount_string() -> None:
    ticket = _ticket(
        decision="PARTIAL",
        approved_amount=decimal.Decimal("1000.00"),
        case_state="DECISION_MADE",
    )
    delivery = build_delivery(ticket, WebhookEvent.CASE_DECIDED, now=_NOW)
    body = json.loads(delivery.payload)

    assert delivery.event == "ticket.case_decided"
    assert body["ticket_number"] == "RH-2026-00001"
    assert body["data"]["decision"] == "PARTIAL"
    assert body["data"]["approved_amount"] == "1000.00"  # строка, не float (FR-9.8)
    assert body["data"]["case_state"] == "DECISION_MADE"
    # ФЗ-152/NFR-1.3: свободный текст оператора НЕ в payload.
    assert "decision_reason" not in body["data"]


def test_payout_released_unconfirmed_until_linked_payment() -> None:
    ticket = _ticket(
        case_state="PAID", approved_amount=decimal.Decimal("500.00"), linked_payment_id=None
    )
    body = json.loads(build_delivery(ticket, WebhookEvent.PAYOUT_RELEASED, now=_NOW).payload)
    # D7: пока нет linked_payment_id — деньги НЕ подтверждены банком.
    assert body["data"]["payment_confirmed"] is False
    assert body["data"]["linked_payment_id"] is None
    assert body["data"]["approved_amount"] == "500.00"


def test_payout_released_confirmed_when_linked_payment_set() -> None:
    payment_id = uuid.uuid4()
    ticket = _ticket(case_state="PAID", linked_payment_id=payment_id)
    body = json.loads(build_delivery(ticket, WebhookEvent.PAYOUT_RELEASED, now=_NOW).payload)
    assert body["data"]["payment_confirmed"] is True
    assert body["data"]["linked_payment_id"] == str(payment_id)


def test_amount_none_serialized_as_null() -> None:
    body = json.loads(
        build_delivery(_ticket(decision="REJECTED"), WebhookEvent.CASE_DECIDED, now=_NOW).payload
    )
    assert body["data"]["approved_amount"] is None


def test_timestamp_matches_now() -> None:
    delivery = build_delivery(_ticket(), WebhookEvent.CASE_DECIDED, now=_NOW)
    assert delivery.timestamp == int(_NOW.timestamp())
