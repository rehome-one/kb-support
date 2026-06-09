"""Fire-after доставка webhook-событий подписчикам (E10-8 PR-B #198; ADR-0015 D3/D4).

Config-gate = есть активные подписки на событие (нет → инертно). Per-подписка свой httpx +
`ResilientHttpClient` (AT-003: timeout→breaker→retry), HMAC-подпись (`signing.py`), **never-raise**
(ФЗ-152: логи только event/delivery_id/status, без тела/секрета/url). Durable доставка — #79.

**Дедуп-маркер НЕ нужен (ADR-0015 У16):** триггеры гарантируют единичность —
`ticket.decision` write-once (нет сброса) → `case_decided` однажды; `case_state=PAID`
терминален → `payout_released` однажды. Вызывать ПОСЛЕ commit (плоские данные подписок —
str url/secret — передаются в фон, ORM-объекты в таск не уходят).
"""

from __future__ import annotations

import datetime

import httpx
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.errors import CircuitOpenError, ExternalServiceError
from api.clients.factory import build_resilient_client
from api.config import Settings
from api.observability.logging import get_logger
from api.tickets.models import Ticket
from api.webhooks.enums import WebhookEvent
from api.webhooks.events import WebhookDelivery, build_delivery
from api.webhooks.repository import WebhookSubscriptionRepository
from api.webhooks.signing import signature_header

_logger = get_logger("webhooks.delivery")

_DELIVER_OP = "webhook.deliver"


def _delivery_headers(delivery: WebhookDelivery, secret: str) -> dict[str, str]:
    """Заголовки доставки: событие/id/timestamp + HMAC-подпись (ADR-0015 D3)."""
    return {
        "Content-Type": "application/json",
        "X-Webhook-Event": delivery.event,
        "X-Webhook-Delivery": str(delivery.delivery_id),
        "X-Webhook-Timestamp": str(delivery.timestamp),
        "X-Signature": signature_header(
            payload=delivery.payload, secret=secret, timestamp=delivery.timestamp
        ),
    }


async def schedule_webhook_event(
    background: BackgroundTasks,
    session: AsyncSession,
    ticket: Ticket,
    event: WebhookEvent,
    settings: Settings,
    *,
    now: datetime.datetime | None = None,
) -> int:
    """Запланировать fire-after доставку события всем активным подпискам.

    Возвращает число запланированных доставок (для тестов). Нет подписок → 0 (инертно).
    Тело конверта строится один раз; в фон уходят только плоские url/secret + DTO."""
    subscriptions = await WebhookSubscriptionRepository(session).list_active_for_event(event.value)
    if not subscriptions:
        return 0
    moment = now if now is not None else datetime.datetime.now(datetime.UTC)
    delivery = build_delivery(ticket, event, now=moment)
    for subscription in subscriptions:
        background.add_task(
            deliver_webhook, subscription.url, subscription.secret, delivery, settings
        )
    return len(subscriptions)


async def deliver_webhook(
    url: str, secret: str, delivery: WebhookDelivery, settings: Settings
) -> None:
    """Фоновая доставка одного события одной подписке. Свой httpx. Никогда не роняет процесс."""
    try:
        async with httpx.AsyncClient(timeout=settings.client_timeout_seconds) as http:
            client = build_resilient_client("webhook", http, settings)
            response = await client.request(
                "POST",
                url,
                operation=_DELIVER_OP,
                content=delivery.payload,
                headers=_delivery_headers(delivery, secret),
            )
        _logger.info(
            "webhook delivered event=%s delivery=%s status=%s",
            delivery.event,
            delivery.delivery_id,
            response.status_code,
        )
    except (ExternalServiceError, CircuitOpenError):
        _logger.warning(
            "webhook delivery failed event=%s delivery=%s", delivery.event, delivery.delivery_id
        )
    except Exception:  # последний рубеж: фоновый таск не должен ронять процесс
        _logger.warning(
            "webhook delivery error event=%s delivery=%s", delivery.event, delivery.delivery_id
        )
