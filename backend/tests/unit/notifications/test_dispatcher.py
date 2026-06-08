"""Unit-тесты диспетчера уведомлений (E7-8, #149) — без сети и БД.

ORM-объекты в памяти; реальный BackgroundTasks (его `.tasks` инспектируется). Покрывают:
fan-out ответа по каналам + изоляцию сбоя; решение/дедуп/сброс маркера статус-уведомления
(M2); подавление само-спама; NFR-1.3.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import BackgroundTasks

from api.config import Settings
from api.notifications import dispatcher
from api.notifications.dedup import last_status_notified
from api.notifications.dispatcher import (
    StatusNotice,
    notify_message,
    prepare_status_notification,
    schedule_status_notification,
)
from api.notifications.labels import status_label
from api.tickets.enums import AuthorType, TicketChannel, TicketStatus
from api.tickets.messages import TicketMessage
from api.tickets.models import Ticket

_REQUESTER = uuid.uuid4()
_OPERATOR = uuid.uuid4()


def _ticket(
    *, status: str = TicketStatus.OPEN.value, channel: str = TicketChannel.EMAIL.value
) -> Ticket:
    return Ticket(
        id=uuid.uuid4(),
        number="RH-2026-00042",
        subject="Оплата",
        status=status,
        channel=channel,
        requester_id=_REQUESTER,
        custom_fields={"email_from": "req@example.com"},
    )


def _message(*, internal: bool = False) -> TicketMessage:
    return TicketMessage(
        id=uuid.uuid4(), author_type=AuthorType.OPERATOR.value, is_internal=internal, body="ответ"
    )


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "smtp_host": "smtp.test",
        "smtp_from_address": "support@rehome.one",
        "kb_search_api_token": "tok",
    }
    base.update(over)
    return Settings(**base)


# --- notify_message (fan-out ответа) ---


def test_notify_message_fans_out_to_email_for_email_ticket() -> None:
    bg = BackgroundTasks()
    notify_message(bg, _ticket(channel=TicketChannel.EMAIL.value), _message(), _settings())
    assert len(bg.tasks) == 1  # email-канал запланирован (chat не для EMAIL-заявки)


def test_notify_message_internal_note_no_fanout() -> None:
    # NFR-1.3: внутренняя заметка не уходит ни в один канал.
    bg = BackgroundTasks()
    notify_message(bg, _ticket(), _message(internal=True), _settings())
    assert bg.tasks == []


def test_notify_message_channel_failure_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    bg = BackgroundTasks()

    def _boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("channel boom")

    # email-канал падает на планировании — chat-канал (для AI_CHAT) всё равно отрабатывает.
    monkeypatch.setattr(dispatcher, "maybe_schedule_email", _boom)
    t = _ticket(channel=TicketChannel.AI_CHAT.value)
    t.chat_session_id = uuid.uuid4()
    notify_message(bg, t, _message(), _settings())
    assert len(bg.tasks) == 1  # chat запланирован несмотря на сбой email-канала (изоляция)


# --- prepare_status_notification (решение + дедуп + M2) ---


def test_status_change_to_resolved_notifies_and_marks() -> None:
    t = _ticket(status=TicketStatus.RESOLVED.value)
    notice = prepare_status_notification(t, TicketStatus.OPEN.value, _OPERATOR)
    assert notice is not None
    assert notice.new_status == TicketStatus.RESOLVED.value
    assert last_status_notified(t) == TicketStatus.RESOLVED.value  # маркер записан (реассайн)


def test_status_no_change_no_notice() -> None:
    t = _ticket(status=TicketStatus.RESOLVED.value)
    assert prepare_status_notification(t, TicketStatus.RESOLVED.value, _OPERATOR) is None


def test_status_non_notified_clears_marker() -> None:
    # M2: переход на НЕуведомляемый статус сбрасывает маркер.
    t = _ticket(status=TicketStatus.RESOLVED.value)
    prepare_status_notification(t, TicketStatus.OPEN.value, _OPERATOR)  # маркер=RESOLVED
    t.status = TicketStatus.REOPENED.value
    assert prepare_status_notification(t, TicketStatus.RESOLVED.value, _OPERATOR) is None
    assert last_status_notified(t) is None  # сброшен


def test_status_re_transition_notifies_twice() -> None:
    # M2: RESOLVED → REOPENED → RESOLVED должен уведомить ОБА раза.
    t = _ticket(status=TicketStatus.RESOLVED.value)
    assert prepare_status_notification(t, TicketStatus.OPEN.value, _OPERATOR) is not None
    t.status = TicketStatus.REOPENED.value
    prepare_status_notification(t, TicketStatus.RESOLVED.value, _OPERATOR)  # сброс маркера
    t.status = TicketStatus.RESOLVED.value
    assert prepare_status_notification(t, TicketStatus.REOPENED.value, _OPERATOR) is not None


def test_status_dedup_same_status() -> None:
    t = _ticket(status=TicketStatus.RESOLVED.value)
    prepare_status_notification(t, TicketStatus.OPEN.value, _OPERATOR)
    # Повторный вызов с тем же итоговым статусом (без сброса) — дедуп.
    assert prepare_status_notification(t, TicketStatus.PENDING.value, _OPERATOR) is None


def test_status_change_by_requester_suppressed() -> None:
    # Заявитель сам закрыл свою заявку → не уведомляем его же (анти-само-спам).
    t = _ticket(status=TicketStatus.CLOSED.value)
    assert prepare_status_notification(t, TicketStatus.OPEN.value, _REQUESTER) is None


# --- schedule_status_notification (каналы) ---


def test_schedule_status_email_for_email_ticket() -> None:
    bg = BackgroundTasks()
    t = _ticket(status=TicketStatus.RESOLVED.value, channel=TicketChannel.EMAIL.value)
    schedule_status_notification(bg, t, StatusNotice(TicketStatus.RESOLVED.value), _settings())
    assert len(bg.tasks) == 1  # email канал (chat не для EMAIL)


def test_schedule_status_chat_for_ai_chat_ticket() -> None:
    bg = BackgroundTasks()
    t = _ticket(status=TicketStatus.RESOLVED.value, channel=TicketChannel.AI_CHAT.value)
    t.chat_session_id = uuid.uuid4()
    schedule_status_notification(bg, t, StatusNotice(TicketStatus.RESOLVED.value), _settings())
    assert len(bg.tasks) == 1  # chat канал


def test_schedule_status_off_without_config() -> None:
    bg = BackgroundTasks()
    t = _ticket(status=TicketStatus.RESOLVED.value, channel=TicketChannel.EMAIL.value)
    schedule_status_notification(
        bg, t, StatusNotice(TicketStatus.RESOLVED.value), _settings(smtp_host="")
    )
    assert bg.tasks == []  # config-gate выключил email


def test_status_label_known_and_fallback() -> None:
    assert status_label(TicketStatus.RESOLVED.value) == "Решена"
    assert status_label("UNKNOWN") == "UNKNOWN"


# --- dispatch_status_to_chat (фоновая доставка, без сети) ---


def _notification() -> Any:
    from api.clients.kb_search import StatusNotification

    return StatusNotification(
        chat_session_id=uuid.uuid4(),
        ticket_id=uuid.uuid4(),
        status=TicketStatus.RESOLVED.value,
        status_label="Решена",
    )


@pytest.mark.asyncio
async def test_dispatch_status_to_chat_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.clients.kb_search import ReplyOutcome

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None: ...

        async def send_status_notification(self, notification: Any) -> ReplyOutcome:
            return ReplyOutcome.DELIVERED

    monkeypatch.setattr(dispatcher, "HttpKbSearchClient", _FakeClient)
    # Не бросает; реальная сеть не дёргается (клиент-метод замокан).
    await dispatcher.dispatch_status_to_chat(_notification(), _settings())


@pytest.mark.asyncio
async def test_dispatch_status_to_chat_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomClient:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("kb-search down")

    monkeypatch.setattr(dispatcher, "HttpKbSearchClient", _BoomClient)
    # Фоновый таск не должен ронять процесс.
    await dispatcher.dispatch_status_to_chat(_notification(), _settings())
