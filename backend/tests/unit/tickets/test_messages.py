"""Unit-тесты сообщений: схемы и хелперы (без БД)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from pydantic import ValidationError

from api.tickets.messages import TicketMessage, message_added_payload
from api.tickets.schemas import TicketMessageCreate, TicketMessageRead


def test_create_minimal_valid() -> None:
    msg = TicketMessageCreate(body="Привет")
    assert msg.body == "Привет"
    assert msg.is_internal is False
    assert msg.attachments is None
    assert msg.canned_response_id is None


def test_create_requires_body() -> None:
    with pytest.raises(ValidationError):
        TicketMessageCreate.model_validate({"is_internal": True})


def test_create_rejects_empty_body() -> None:
    with pytest.raises(ValidationError):
        TicketMessageCreate.model_validate({"body": ""})


def test_create_forbids_extra_fields() -> None:
    # author_id/author_type не принимаются от клиента (anti-spoofing).
    with pytest.raises(ValidationError):
        TicketMessageCreate.model_validate({"body": "x", "author_type": "operator"})


def test_create_accepts_canned_response_id() -> None:
    cid = uuid.uuid4()
    msg = TicketMessageCreate.model_validate({"body": "x", "canned_response_id": str(cid)})
    assert msg.canned_response_id == cid


def test_read_serializes() -> None:
    now = datetime.datetime(2026, 5, 30, tzinfo=datetime.UTC)
    obj = TicketMessage(
        id=uuid.uuid4(),
        ticket_id=uuid.uuid4(),
        author_id=uuid.uuid4(),
        author_type="operator",
        body="hi",
        is_internal=True,
        attachments=[str(uuid.uuid4())],
    )
    obj.created_at = now
    read = TicketMessageRead.model_validate(obj)
    assert read.is_internal is True
    assert read.author_type.value == "operator"
    assert len(read.attachments) == 1


def test_message_added_payload() -> None:
    message = TicketMessage(id=uuid.uuid4(), ticket_id=uuid.uuid4(), body="x", is_internal=True)
    payload = message_added_payload(message)
    assert payload == {"message_id": str(message.id), "is_internal": True}


def test_message_repr() -> None:
    message = TicketMessage(ticket_id=uuid.uuid4(), body="x", is_internal=False)
    rendered = repr(message)
    assert rendered.startswith("<TicketMessage ")
    assert "is_internal" in rendered
