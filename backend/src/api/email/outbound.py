"""Отправка ответа оператора на EMAIL-заявку по SMTP (E7-5, #147). Зеркалит #72.

NFR-1.3 (критичный security-инвариант): письмом уходит ТОЛЬКО публичный ответ
оператора по заявке `channel=EMAIL` с известным адресом отправителя. Внутренние
заметки (`is_internal=true`) и реплики заявителя НИКОГДА не отправляются. Флаги —
из сохранённого сообщения (ORM), не из payload (anti-spoofing).

Доставка — FastAPI BackgroundTasks (fire-after-response, решение Архитектора, как #72):
фоновый таск получает плоский DTO простых значений (извлечён синхронно в эндпоинте,
пока жива request-сессия) и открывает СВОЙ SMTP-коннект — никаких ORM-объектов/
request-сессии в фоне. `dispatch_email` — sync (smtplib блокирующий → FastAPI гонит
sync background-таск в threadpool, не блокируя loop). Durable-доставка (Dramatiq) —
follow-up #79. ФЗ-152: тело/адрес в логи не пишем — только ticket_number/message_id.
"""

from __future__ import annotations

import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage

from fastapi import BackgroundTasks

from api.config import Settings
from api.observability.logging import get_logger
from api.tickets.enums import TicketChannel
from api.tickets.messages import TicketMessage, is_public_operator_reply
from api.tickets.models import Ticket

_logger = get_logger("email.outbound")


@dataclass(frozen=True)
class OutboundEmail:
    """Плоский DTO исходящего письма (простые значения, извлекается пока жива сессия)."""

    to_addr: str
    subject: str
    body: str
    in_reply_to: str | None
    ticket_number: str
    message_id: uuid.UUID


def email_recipient(ticket: Ticket) -> str:
    """Адрес заявителя из метаданных входящего письма (#145). Пусто → отправки нет.
    Публичный — переиспользуется диспетчером уведомлений (#149)."""
    cf = ticket.custom_fields or {}
    addr = cf.get("email_from")
    return addr if isinstance(addr, str) else ""


def should_send_email(ticket: Ticket, message: TicketMessage) -> bool:
    """NFR-1.3 gate. True только для публичного ответа оператора по EMAIL-заявке с
    известным адресом получателя. Флаги читаются из сохранённого сообщения."""
    return (
        is_public_operator_reply(message)
        and ticket.channel == TicketChannel.EMAIL.value
        and bool(email_recipient(ticket))
    )


def build_outbound_email(ticket: Ticket, message: TicketMessage) -> OutboundEmail:
    """Плоский DTO из простых значений (синхронно, пока жива сессия). Вызывать только
    после `should_send_email` (гарантирует непустой адрес). Subject несёт номер заявки —
    ответ заявителя привяжется входящим приёмом (#145, regex номера). In-Reply-To —
    только при наличии исходного Message-ID (иначе заголовок не ставим)."""
    cf = ticket.custom_fields or {}
    mid = cf.get("email_message_id")
    return OutboundEmail(
        to_addr=email_recipient(ticket),
        subject=f"Re: {ticket.subject} [{ticket.number}]",
        body=message.body,
        in_reply_to=mid if isinstance(mid, str) and mid else None,
        ticket_number=ticket.number,
        message_id=message.id,
    )


def maybe_schedule_email(
    background: BackgroundTasks,
    ticket: Ticket,
    message: TicketMessage,
    settings: Settings,
) -> bool:
    """Запланировать фоновую отправку, если включено и сообщение элигибельно.
    Возвращает факт планирования (для тестов). Извлечение DTO — синхронно здесь.
    Best-effort: само планирование не должно валить ответ 201 эндпоинта."""
    if not settings.smtp_host:  # config-gate: без relay отправка выключена (до ops)
        return False
    if not should_send_email(ticket, message):
        return False
    email = build_outbound_email(ticket, message)
    background.add_task(dispatch_email, email, settings)
    return True


def dispatch_email(email: OutboundEmail, settings: Settings) -> None:
    """Фоновая отправка письма. Свой SMTP-коннект (STARTTLS, проверка сертификата).
    Никогда не роняет процесс — best-effort (durable — follow-up #79)."""
    try:
        message = EmailMessage()
        message["From"] = settings.smtp_from_address
        message["To"] = email.to_addr
        message["Subject"] = email.subject
        if email.in_reply_to:
            message["In-Reply-To"] = email.in_reply_to
            message["References"] = email.in_reply_to
        message.set_content(email.body)

        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.client_timeout_seconds
        ) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        _logger.info(
            "operator reply -> email sent ticket=%s message=%s",
            email.ticket_number,
            email.message_id,
        )
    except Exception:  # последний рубеж: фоновый таск не должен ронять процесс
        _logger.warning(
            "operator reply email dispatch failed: ticket=%s message=%s",
            email.ticket_number,
            email.message_id,
        )
