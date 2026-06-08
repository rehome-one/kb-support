"""Unit-тесты исходящего SMTP-ответа (E7-5, #147) — без сети и БД.

ORM-объекты строятся в памяти; smtplib замокан. Покрывают NFR-1.3 gate (все ветки),
сборку DTO/MIME (Subject несёт номер, In-Reply-To только при Message-ID) и
best-effort dispatch (никогда не роняет процесс).
"""

from __future__ import annotations

import uuid
from email.message import EmailMessage
from typing import Any

import pytest

from api.config import Settings
from api.email.outbound import (
    OutboundEmail,
    build_outbound_email,
    dispatch_email,
    maybe_schedule_email,
    should_send_email,
)
from api.tickets.enums import AuthorType, TicketChannel
from api.tickets.messages import TicketMessage
from api.tickets.models import Ticket


def _ticket(
    *,
    channel: str = TicketChannel.EMAIL.value,
    email_from: str | None = "req@example.com",
    message_id: str | None = "<orig@mail>",
) -> Ticket:
    cf: dict[str, Any] = {}
    if email_from is not None:
        cf["email_from"] = email_from
    if message_id is not None:
        cf["email_message_id"] = message_id
    return Ticket(
        id=uuid.uuid4(), number="RH-2026-00042", subject="Оплата", channel=channel, custom_fields=cf
    )


def _message(
    *, operator: bool = True, internal: bool = False, body: str = "ответ"
) -> TicketMessage:
    return TicketMessage(
        id=uuid.uuid4(),
        author_type=(AuthorType.OPERATOR if operator else AuthorType.REQUESTER).value,
        is_internal=internal,
        body=body,
    )


def test_gate_true_for_operator_public_reply_on_email_ticket() -> None:
    assert should_send_email(_ticket(), _message()) is True


def test_gate_false_for_internal_note() -> None:
    # NFR-1.3: внутренняя заметка НЕ уходит письмом.
    assert should_send_email(_ticket(), _message(internal=True)) is False


def test_gate_false_for_requester_message() -> None:
    assert should_send_email(_ticket(), _message(operator=False)) is False


def test_gate_false_for_non_email_channel() -> None:
    assert should_send_email(_ticket(channel=TicketChannel.AI_CHAT.value), _message()) is False


def test_gate_false_without_recipient() -> None:
    assert should_send_email(_ticket(email_from=None), _message()) is False
    assert should_send_email(_ticket(email_from=""), _message()) is False


def test_build_dto_carries_number_and_recipient() -> None:
    dto = build_outbound_email(_ticket(), _message(body="готово"))
    assert dto.to_addr == "req@example.com"
    assert dto.subject == "Re: Оплата [RH-2026-00042]"  # номер в Subject → threading #145
    assert dto.body == "готово"
    assert dto.in_reply_to == "<orig@mail>"


def test_build_dto_no_in_reply_to_without_message_id() -> None:
    dto = build_outbound_email(_ticket(message_id=None), _message())
    assert dto.in_reply_to is None


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "smtp_host": "smtp.test",
        "smtp_from_address": "support@rehome.one",
        "smtp_username": "",
    }
    base.update(over)
    return Settings(**base)


class _FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.started_tls = False
        self.logged_in = False

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = True

    def send_message(self, message: EmailMessage) -> None:
        _FakeSMTP.sent.append(message)


def test_dispatch_builds_and_sends_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSMTP.sent = []
    monkeypatch.setattr("api.email.outbound.smtplib.SMTP", _FakeSMTP)
    dto = OutboundEmail(
        to_addr="req@example.com",
        subject="Re: Оплата [RH-2026-00042]",
        body="текст ответа",
        in_reply_to="<orig@mail>",
        ticket_number="RH-2026-00042",
        message_id=uuid.uuid4(),
    )
    dispatch_email(dto, _settings(smtp_username="user", smtp_password="pass"))
    assert len(_FakeSMTP.sent) == 1
    sent = _FakeSMTP.sent[0]
    assert sent["To"] == "req@example.com"
    assert sent["From"] == "support@rehome.one"
    assert sent["Subject"] == "Re: Оплата [RH-2026-00042]"
    assert sent["In-Reply-To"] == "<orig@mail>"
    assert sent.get_content().strip() == "текст ответа"


def test_dispatch_never_raises_on_smtp_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomSMTP(_FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise OSError("smtp down")

    monkeypatch.setattr("api.email.outbound.smtplib.SMTP", _BoomSMTP)
    dto = OutboundEmail(
        to_addr="r@x.com",
        subject="Re: x [RH-2026-00001]",
        body="b",
        in_reply_to=None,
        ticket_number="RH-2026-00001",
        message_id=uuid.uuid4(),
    )
    # Не должно бросить (best-effort фоновый таск).
    dispatch_email(dto, _settings())


class _FakeBackground:
    def __init__(self) -> None:
        self.tasks: list[tuple[Any, tuple[Any, ...]]] = []

    def add_task(self, func: Any, *args: Any) -> None:
        self.tasks.append((func, args))


def test_maybe_schedule_off_without_smtp_host() -> None:
    bg = _FakeBackground()
    assert maybe_schedule_email(bg, _ticket(), _message(), _settings(smtp_host="")) is False  # type: ignore[arg-type]
    assert bg.tasks == []


def test_maybe_schedule_schedules_when_enabled_and_eligible() -> None:
    bg = _FakeBackground()
    assert maybe_schedule_email(bg, _ticket(), _message(), _settings()) is True  # type: ignore[arg-type]
    assert len(bg.tasks) == 1


def test_maybe_schedule_skips_internal_note() -> None:
    bg = _FakeBackground()
    # NFR-1.3 на уровне планирования: internal-заметка не ставит задачу отправки.
    assert maybe_schedule_email(bg, _ticket(), _message(internal=True), _settings()) is False  # type: ignore[arg-type]
    assert bg.tasks == []
