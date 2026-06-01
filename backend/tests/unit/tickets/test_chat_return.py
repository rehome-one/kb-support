"""Тесты chat-bridge триггера возврата ответа в kb-search (E3-4, #72).

Фокус — NFR-1.3 gate (внутренняя заметка/заявитель/не-AI_CHAT/без сессии НЕ
возвращаются) и config-gate планирования. БД не нужна: ORM-объекты строятся
в памяти, BackgroundTasks — реальный (инспектируем `.tasks`)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi import BackgroundTasks

import api.tickets.chat_return as chat_return
from api.clients.kb_search.models import OperatorReply, ReplyOutcome
from api.config import Settings
from api.tickets.chat_return import (
    dispatch_operator_reply,
    maybe_schedule_return,
    should_return_to_chat,
)
from api.tickets.enums import AuthorType, TicketChannel
from api.tickets.messages import TicketMessage
from api.tickets.models import Ticket


def _ticket(
    *,
    channel: str = TicketChannel.AI_CHAT.value,
    chat_session_id: uuid.UUID | None = None,
) -> Ticket:
    return Ticket(
        id=uuid.uuid4(),
        channel=channel,
        chat_session_id=chat_session_id if chat_session_id is not None else uuid.uuid4(),
    )


def _message(
    *, author_type: str = AuthorType.OPERATOR.value, is_internal: bool = False
) -> TicketMessage:
    return TicketMessage(
        id=uuid.uuid4(),
        body="Ответ оператора",
        author_type=author_type,
        is_internal=is_internal,
        created_at=datetime.datetime(2026, 6, 2, 10, 0, tzinfo=datetime.UTC),
    )


# --- NFR-1.3 gate ---


def test_eligible_operator_public_ai_chat() -> None:
    assert should_return_to_chat(_ticket(), _message()) is True


def test_internal_note_not_returned() -> None:
    # КРИТИЧНО (NFR-1.3): внутренняя заметка оператора НЕ уходит в чат.
    assert should_return_to_chat(_ticket(), _message(is_internal=True)) is False


def test_requester_message_not_returned() -> None:
    assert (
        should_return_to_chat(_ticket(), _message(author_type=AuthorType.REQUESTER.value)) is False
    )


def test_non_ai_chat_not_returned() -> None:
    assert should_return_to_chat(_ticket(channel=TicketChannel.EMAIL.value), _message()) is False


def test_no_chat_session_not_returned() -> None:
    ticket = Ticket(id=uuid.uuid4(), channel=TicketChannel.AI_CHAT.value, chat_session_id=None)
    assert should_return_to_chat(ticket, _message()) is False


# --- config-gate планирования ---


def _settings(token: str) -> Settings:
    return Settings(kb_search_api_token=token, kb_search_api_base_url="http://kb-search")


def test_schedules_when_enabled_and_eligible() -> None:
    bg = BackgroundTasks()
    scheduled = maybe_schedule_return(bg, _ticket(), _message(), _settings("m2m-token"))
    assert scheduled is True
    assert len(bg.tasks) == 1


def test_not_scheduled_when_token_empty() -> None:
    # Gate: пустой токен (#77 не готов) → возврат выключен, даже если элигибельно.
    bg = BackgroundTasks()
    scheduled = maybe_schedule_return(bg, _ticket(), _message(), _settings(""))
    assert scheduled is False
    assert bg.tasks == []


def test_not_scheduled_for_internal_note_even_if_enabled() -> None:
    # КРИТИЧНО: даже при включённой функции внутренняя заметка не планируется.
    bg = BackgroundTasks()
    scheduled = maybe_schedule_return(
        bg, _ticket(), _message(is_internal=True), _settings("m2m-token")
    )
    assert scheduled is False
    assert bg.tasks == []


# --- фоновая доставка (dispatch) ---


def _reply() -> OperatorReply:
    return OperatorReply(
        chat_session_id=uuid.uuid4(),
        ticket_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        body="Ответ",
        sent_at=datetime.datetime(2026, 6, 2, 10, 0, tzinfo=datetime.UTC),
    )


async def test_dispatch_runs_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def __init__(self, **_: object) -> None: ...

        async def send_operator_reply(self, reply: OperatorReply) -> ReplyOutcome:
            return ReplyOutcome.DELIVERED

    monkeypatch.setattr(chat_return, "HttpKbSearchClient", _FakeClient)
    # Не должно бросить (httpx-клиент создаётся, но сетевой вызов идёт в фейк).
    await dispatch_operator_reply(_reply(), _settings("m2m-token"))


async def test_dispatch_swallows_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomClient:
        def __init__(self, **_: object) -> None: ...

        async def send_operator_reply(self, reply: OperatorReply) -> ReplyOutcome:
            raise RuntimeError("unexpected")

    monkeypatch.setattr(chat_return, "HttpKbSearchClient", _BoomClient)
    # Последний рубеж: фоновый таск не должен пробросить исключение.
    await dispatch_operator_reply(_reply(), _settings("m2m-token"))
