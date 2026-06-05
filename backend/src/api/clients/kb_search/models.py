"""Доменные модели возврата ответа оператора в kb-search (E3-4, #72).

`OperatorReply` — плоский DTO простых значений, извлечённых синхронно в эндпоинте
ДО планирования фонового таска (никаких ORM-объектов в фоне — иначе
DetachedInstanceError, см. ревью плана MAJOR-1). `ReplyOutcome` — исход доставки.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from dataclasses import dataclass


class ReplyOutcome(str, enum.Enum):
    """Исход возврата ответа в chat-session (ADR-0006 Решение 3)."""

    DELIVERED = "delivered"  # 202 — принято к доставке
    SESSION_GONE = "session_gone"  # 404/409 — сессия истекла/закрыта (деградация)
    DEGRADED = "degraded"  # сетевой сбой / circuit-open (деградация)


@dataclass(frozen=True)
class OperatorReply:
    """Ответ оператора к возврату в chat-session. Только простые значения."""

    chat_session_id: uuid.UUID
    ticket_id: uuid.UUID
    message_id: uuid.UUID
    body: str
    sent_at: datetime.datetime


@dataclass(frozen=True)
class ArticleSuggestion:
    """Предложенная статья базы знаний (E6-6, #130). Без ПДн — публичный контент БЗ."""

    slug: str
    title: str
    url: str | None
