"""Диспетчер уведомлений заявителю (E7-8, #149) — единая точка fan-out.

Решение A (унификация): `notify_message` — единственная точка веера для ответа
оператора (chat #72 + email #147 + будущие push/SMS #150). Решение B: смена статуса
(`prepare_status_notification` + `schedule_status_notification`). Каждый канал — best-effort
изолированно (сбой одного не валит прочие, паттерн #72/#107). NFR-1.3: ответ-канал
наследует gate'ы (`is_internal` не уходит); статус-уведомление оперирует статусом, не
сообщением. ФЗ-152: тела/адреса/сессии в логи не пишем — только идентификаторы/статус.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import httpx
from fastapi import BackgroundTasks

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_search import HttpKbSearchClient, StatusNotification
from api.clients.retry import RetryPolicy
from api.config import Settings
from api.email.outbound import (
    OutboundEmail,
    dispatch_email,
    email_recipient,
    maybe_schedule_email,
)
from api.notifications.channels import maybe_schedule_push, maybe_schedule_sms
from api.notifications.dedup import (
    clear_status_notified,
    last_status_notified,
    set_status_notified,
)
from api.notifications.labels import NOTIFIED_STATUSES, status_label
from api.observability.logging import get_logger
from api.tickets.chat_return import maybe_schedule_return
from api.tickets.enums import TicketChannel
from api.tickets.messages import TicketMessage, is_public_operator_reply
from api.tickets.models import Ticket

_logger = get_logger("notifications")

# Низкая оценка (FR-8.2) — балл ≤ этого порога (ADR-0012 D4).
_LOW_RATING_MAX = 2


def notify_low_rating(background: BackgroundTasks, ticket: Ticket, settings: Settings) -> None:
    """FR-8.2: уведомить супервайзера о низкой оценке (1-2) — fire-after, best-effort.

    Config-gated seam (ADR-0012 D2): адресат — `settings.low_rating_notify_email` (НЕ
    заявитель), gate по нему И `smtp_host`. Балл ≤ `_LOW_RATING_MAX`. Сбой планирования
    изолирован — НЕ роняет `rate`. ФЗ-152 (D6): `rating_comment` в лог не пишем; в теле
    письма супервайзеру (внутренний контур) допустим.
    """
    rating = ticket.rating
    if rating is None or rating > _LOW_RATING_MAX:
        return
    recipient = settings.low_rating_notify_email
    if not recipient or not settings.smtp_host:  # seam инертен до ops
        return
    try:
        comment = ticket.rating_comment
        body = f"Заявка {ticket.number} получила низкую оценку: {rating}/5."
        if comment:
            body += f"\n\nКомментарий заявителя:\n{comment}"
        email = OutboundEmail(
            to_addr=recipient,
            subject=f"Низкая оценка [{ticket.number}]: {rating}/5",
            body=body,
            in_reply_to=None,
            ticket_number=ticket.number,
            message_id=uuid.uuid4(),  # у уведомления нет сообщения — id для лог-корреляции
        )
        background.add_task(dispatch_email, email, settings)
    except Exception:  # изоляция — уведомление не должно ронять rate (best-effort, #72)
        _logger.warning("low-rating notify failed to schedule ticket=%s", ticket.number)


def notify_message(
    background: BackgroundTasks, ticket: Ticket, message: TicketMessage, settings: Settings
) -> None:
    """Веер уведомления о новом сообщении (ответ оператора) по каналам. Best-effort:
    сбой планирования одного канала не мешает прочим. chat/email наследуют свои gate'ы
    (NFR-1.3, config-gate)."""
    for channel, schedule in (
        ("chat", maybe_schedule_return),
        ("email", maybe_schedule_email),
    ):
        try:
            schedule(background, ticket, message, settings)
        except Exception:  # изоляция канала — один сбой не валит остальные
            _logger.warning("notify_message channel failed: %s", channel)
    # push/SMS seam'ы (#150): у них нет message-based gate, поэтому NFR-1.3 проверяем здесь —
    # уведомляем только о ПУБЛИЧНОМ ответе оператора (внутренняя заметка → ни push, ни SMS).
    if is_public_operator_reply(message):
        _fan_out_push_sms(background, ticket, "Новый ответ оператора", settings)


def _fan_out_push_sms(
    background: BackgroundTasks, ticket: Ticket, summary: str, settings: Settings
) -> None:
    """Веер seam-каналов push/SMS (#150), best-effort изолированно. Дедуп — общий для
    события (per-status маркер #149, не per-channel): push/SMS делят то же решение."""
    for channel, schedule in (("push", maybe_schedule_push), ("sms", maybe_schedule_sms)):
        try:
            schedule(background, ticket, summary, settings)
        except Exception:
            _logger.warning("push/sms channel failed: %s", channel)


@dataclass(frozen=True)
class StatusNotice:
    """Решение «уведомить о смене статуса» (новый статус для веера по каналам)."""

    new_status: str


def prepare_status_notification(
    ticket: Ticket, old_status: str, actor_id: uuid.UUID
) -> StatusNotice | None:
    """Решить, нужно ли уведомить о смене статуса, и обновить дедуп-маркер (в текущей
    транзакции). Возвращает решение или None. Маркер пишется РЕАССАЙНОМ (M1).

    Правила: реальная смена (old≠new); new ∈ NOTIFIED_STATUSES; актор ≠ заявитель
    (не само-спам); не дублировать тот же статус (дедуп). При переходе на НЕуведомляемый
    статус — сбросить маркер (M2), чтобы возврат к уведомляемому снова сработал."""
    new_status = ticket.status
    if new_status == old_status:
        return None
    if new_status not in NOTIFIED_STATUSES:
        clear_status_notified(ticket)  # M2: сброс при переходе прочь
        return None
    if actor_id == ticket.requester_id:
        return None  # заявитель сам сменил статус — не уведомляем его же
    if last_status_notified(ticket) == new_status:
        return None  # дедуп: об этом статусе уже уведомили
    set_status_notified(ticket, new_status)
    return StatusNotice(new_status=new_status)


def schedule_status_notification(
    background: BackgroundTasks, ticket: Ticket, notice: StatusNotice, settings: Settings
) -> None:
    """Веер статус-уведомления по каналам (email + chat). Best-effort per-channel."""
    try:
        _schedule_status_email(background, ticket, notice.new_status, settings)
    except Exception:
        _logger.warning("status notify channel failed: email")
    try:
        _schedule_status_chat(background, ticket, notice.new_status, settings)
    except Exception:
        _logger.warning("status notify channel failed: chat")
    # push/SMS seam'ы (#150): сводка — RU-лейбл нового статуса (без ПДн).
    _fan_out_push_sms(background, ticket, status_label(notice.new_status), settings)


def _schedule_status_email(
    background: BackgroundTasks, ticket: Ticket, new_status: str, settings: Settings
) -> None:
    if not settings.smtp_host:  # config-gate как у reply-email (#147)
        return
    if ticket.channel != TicketChannel.EMAIL.value:
        return
    recipient = email_recipient(ticket)
    if not recipient:
        return
    cf = ticket.custom_fields or {}
    mid = cf.get("email_message_id")
    label = status_label(new_status)
    email = OutboundEmail(
        to_addr=recipient,
        subject=f"Заявка [{ticket.number}]: {label}",
        body=f"Статус вашей заявки {ticket.number} изменён: {label}.",
        in_reply_to=mid if isinstance(mid, str) and mid else None,
        ticket_number=ticket.number,
        message_id=uuid.uuid4(),  # у статуса нет сообщения — id только для лог-корреляции
    )
    background.add_task(dispatch_email, email, settings)


def _schedule_status_chat(
    background: BackgroundTasks, ticket: Ticket, new_status: str, settings: Settings
) -> None:
    if not settings.kb_search_api_token:  # config-gate как у reply-chat (#72)
        return
    if ticket.channel != TicketChannel.AI_CHAT.value:
        return
    if ticket.chat_session_id is None:
        return
    notification = StatusNotification(
        chat_session_id=ticket.chat_session_id,
        ticket_id=ticket.id,
        status=new_status,
        status_label=status_label(new_status),
    )
    background.add_task(dispatch_status_to_chat, notification, settings)


async def dispatch_status_to_chat(notification: StatusNotification, settings: Settings) -> None:
    """Фоновая доставка статус-уведомления в chat-session. Свой kb-search клиент (не
    request-сессия). Никогда не роняет процесс — best-effort (durable — follow-up #79)."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.kb_search_api_base_url, timeout=settings.client_timeout_seconds
        ) as http:
            resilient = ResilientHttpClient(
                client_name="kb_search",
                http=http,
                breaker=CircuitBreaker(
                    failure_threshold=settings.client_breaker_failure_threshold,
                    reset_timeout=settings.client_breaker_reset_timeout,
                    now=time.monotonic,
                ),
                retry=RetryPolicy(
                    attempts=settings.client_retry_attempts,
                    base_delay=settings.client_retry_base_delay,
                    max_delay=settings.client_retry_max_delay,
                ),
            )
            client = HttpKbSearchClient(
                http_client=resilient,
                token_provider=StaticTokenProvider(settings.kb_search_api_token),
            )
            outcome = await client.send_status_notification(notification)
        _logger.info(
            "status notify -> chat: %s session=%s ticket=%s",
            outcome.value,
            notification.chat_session_id,
            notification.ticket_id,
        )
    except Exception:  # последний рубеж: фоновый таск не роняет процесс
        _logger.warning(
            "status notify chat dispatch failed: session=%s ticket=%s",
            notification.chat_session_id,
            notification.ticket_id,
        )
