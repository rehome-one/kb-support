"""Триггер возврата ответа оператора в kb-search (E3-4, #72). chat-bridge.

NFR-1.3 (критичный security-инвариант): в чат уходит ТОЛЬКО публичный ответ
оператора по AI_CHAT-заявке с непустым chat_session_id. Источник флагов —
сохранённое сообщение (ORM), не входной payload (anti-spoofing). Внутренние
заметки (`is_internal=true`) НИКОГДА не возвращаются.

Доставка — FastAPI BackgroundTasks (fire-after-response, решение Архитектора):
фоновый таск получает плоский DTO простых значений (извлечён синхронно в
эндпоинте, пока жива request-сессия) и создаёт СВОЙ httpx-клиент — никаких
ORM-объектов / request-сессии в фоне. Durable-доставка (Dramatiq) — follow-up #79.
"""

from __future__ import annotations

import time

import httpx
from fastapi import BackgroundTasks

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_search import HttpKbSearchClient, OperatorReply
from api.clients.retry import RetryPolicy
from api.config import Settings
from api.observability.logging import get_logger
from api.tickets.enums import AuthorType, TicketChannel
from api.tickets.messages import TicketMessage
from api.tickets.models import Ticket

_logger = get_logger("chat_bridge")


def should_return_to_chat(ticket: Ticket, message: TicketMessage) -> bool:
    """NFR-1.3 gate. True только для публичного ответа оператора по AI_CHAT-заявке
    с chat_session_id. Флаги читаются из сохранённого сообщения, не из payload."""
    return (
        message.author_type == AuthorType.OPERATOR.value
        and not message.is_internal
        and ticket.channel == TicketChannel.AI_CHAT.value
        and ticket.chat_session_id is not None
    )


def build_operator_reply(ticket: Ticket, message: TicketMessage) -> OperatorReply:
    """Плоский DTO из простых значений (синхронно, пока жива сессия). Вызывать
    только после `should_return_to_chat` (гарантирует chat_session_id != None)."""
    assert ticket.chat_session_id is not None  # гарантировано should_return_to_chat
    return OperatorReply(
        chat_session_id=ticket.chat_session_id,
        ticket_id=ticket.id,
        message_id=message.id,
        body=message.body,
        sent_at=message.created_at,
    )


def maybe_schedule_return(
    background: BackgroundTasks,
    ticket: Ticket,
    message: TicketMessage,
    settings: Settings,
) -> bool:
    """Запланировать фоновый возврат, если функция включена и сообщение элигибельно.
    Возвращает факт планирования (для тестов). Извлечение DTO — синхронно здесь."""
    # Gate: без реального m2m-токена (#77) возврат в чат выключен (kb_search_api_token
    # имеет ПУСТОЙ дефолт; base_url непустой, поэтому гейтим по токену — ревью MAJOR-2).
    if not settings.kb_search_api_token:
        return False
    if not should_return_to_chat(ticket, message):
        return False
    reply = build_operator_reply(ticket, message)
    background.add_task(dispatch_operator_reply, reply, settings)
    return True


async def dispatch_operator_reply(reply: OperatorReply, settings: Settings) -> None:
    """Фоновая доставка ответа. Свой httpx-клиент (не request-сессия). Никогда не
    роняет процесс — best-effort (durable — follow-up #79)."""
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
            outcome = await client.send_operator_reply(reply)
        _logger.info(
            "operator reply -> kb-search: %s session=%s message=%s",
            outcome.value,
            reply.chat_session_id,
            reply.message_id,
        )
    except Exception:  # последний рубеж: фоновый таск не должен ронять процесс
        _logger.warning(
            "operator reply dispatch failed: session=%s message=%s",
            reply.chat_session_id,
            reply.message_id,
        )
