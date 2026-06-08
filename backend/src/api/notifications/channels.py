"""Config-gated seam-каналы push/SMS уведомлений (E7-9, #150, ADR-0010 Реш.5).

push и SMS — **seam'ы, инертные до ops**: канал включается непустым токеном
(`push_api_token`/`sms_api_token`). Выключен → лог намерения на DEBUG БЕЗ ПДн, задача
НЕ планируется. Включён → планируется фоновый seam-таск, который пока лишь фиксирует
намерение (боевая доставка через Exolve/push-провайдер + резолв телефона/токена через
platform — **follow-up #161** после ops). Каждый канал — best-effort (никогда не роняет
процесс). ФЗ-152: телефон/push-токен (ПДн) здесь НЕ запрашиваются и не логируются —
только ticket_id/номер + нейтральная сводка без ПДн.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import BackgroundTasks

from api.config import Settings
from api.observability.logging import get_logger
from api.tickets.models import Ticket

_logger = get_logger("notifications.channels")


@dataclass(frozen=True)
class PushSmsNotice:
    """Плоский DTO для seam-доставки push/SMS — только не-ПДн значения."""

    ticket_id: uuid.UUID
    ticket_number: str
    summary: str  # нейтральная сводка без ПДн (напр. «Новый ответ», RU-лейбл статуса)


def _notice(ticket: Ticket, summary: str) -> PushSmsNotice:
    return PushSmsNotice(ticket_id=ticket.id, ticket_number=ticket.number, summary=summary)


def maybe_schedule_push(
    background: BackgroundTasks, ticket: Ticket, summary: str, settings: Settings
) -> bool:
    """Запланировать push (seam), если канал включён. Выключен → DEBUG-намерение без ПДн."""
    if not settings.push_api_token:
        _logger.debug("push notification skipped: channel off ticket=%s", ticket.number)
        return False
    background.add_task(dispatch_push, _notice(ticket, summary), settings)
    return True


def maybe_schedule_sms(
    background: BackgroundTasks, ticket: Ticket, summary: str, settings: Settings
) -> bool:
    """Запланировать SMS (seam), если канал включён. Выключен → DEBUG-намерение без ПДн."""
    if not settings.sms_api_token:
        _logger.debug("sms notification skipped: channel off ticket=%s", ticket.number)
        return False
    background.add_task(dispatch_sms, _notice(ticket, summary), settings)
    return True


def dispatch_push(notice: PushSmsNotice, settings: Settings) -> None:
    """Seam push-доставки. Боевой путь (push-провайдер + резолв токена) — follow-up #161.
    Никогда не роняет процесс; ПДн не логирует."""
    # Боевая доставка push — follow-up #161 (после ops: провайдер + резолв push-токена #77).
    _logger.info("push notification pending ops delivery (#161) ticket=%s", notice.ticket_number)


def dispatch_sms(notice: PushSmsNotice, settings: Settings) -> None:
    """Seam SMS-доставки. Боевой путь (Exolve + резолв телефона) — follow-up #161.
    Никогда не роняет процесс; ПДн не логирует."""
    # Боевая доставка SMS через Exolve — follow-up #161 (после ops: creds + резолв телефона #77).
    _logger.info("sms notification pending ops delivery (#161) ticket=%s", notice.ticket_number)
