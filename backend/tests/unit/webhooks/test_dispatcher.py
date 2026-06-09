"""Unit-тесты диспетчера доставки webhook (E10-8 PR-B #198; ADR-0015 D3/D4)."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from typing import cast

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.tickets.models import Ticket
from api.webhooks import dispatcher as dispatcher_module
from api.webhooks.dispatcher import (
    _delivery_headers,
    deliver_webhook,
    schedule_webhook_event,
)
from api.webhooks.enums import WebhookEvent
from api.webhooks.events import WebhookDelivery, build_delivery
from api.webhooks.models import WebhookSubscription
from api.webhooks.signing import compute_signature

_NOW = datetime.datetime(2026, 6, 10, 12, 0, 0, tzinfo=datetime.UTC)


def _ticket() -> Ticket:
    return Ticket(
        id=uuid.uuid4(),
        number="RH-2026-00007",
        decision="FULL",
        approved_amount=None,
        case_state="DECISION_MADE",
        linked_payment_id=None,
    )


def _sub(url: str, secret: str) -> WebhookSubscription:
    return WebhookSubscription(id=uuid.uuid4(), url=url, secret=secret, events=[], is_active=True)


def test_delivery_headers_carry_valid_signature() -> None:
    delivery = build_delivery(_ticket(), WebhookEvent.CASE_DECIDED, now=_NOW)
    headers = _delivery_headers(delivery, "topsecret-value-1234")

    assert headers["X-Webhook-Event"] == "ticket.case_decided"
    assert headers["X-Webhook-Delivery"] == str(delivery.delivery_id)
    assert headers["X-Webhook-Timestamp"] == str(delivery.timestamp)
    expected = compute_signature(
        payload=delivery.payload, secret="topsecret-value-1234", timestamp=delivery.timestamp
    )
    assert headers["X-Signature"] == f"t={delivery.timestamp},v1={expected}"


@pytest.mark.asyncio
async def test_schedule_no_subscriptions_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(self: object, event: str) -> Sequence[WebhookSubscription]:
        return []

    monkeypatch.setattr(
        "api.webhooks.dispatcher.WebhookSubscriptionRepository.list_active_for_event", _none
    )
    background = BackgroundTasks()
    count = await schedule_webhook_event(
        background,
        cast("AsyncSession", None),
        _ticket(),
        WebhookEvent.CASE_DECIDED,
        get_settings(),
    )
    assert count == 0
    assert list(background.tasks) == []


@pytest.mark.asyncio
async def test_schedule_fans_out_to_each_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_sub("https://a.example.com/h", "s1"), _sub("https://b.example.com/h", "s2")]

    async def _subs(self: object, event: str) -> Sequence[WebhookSubscription]:
        return subs

    monkeypatch.setattr(
        "api.webhooks.dispatcher.WebhookSubscriptionRepository.list_active_for_event", _subs
    )
    background = BackgroundTasks()
    count = await schedule_webhook_event(
        background,
        cast("AsyncSession", None),
        _ticket(),
        WebhookEvent.CASE_DECIDED,
        get_settings(),
        now=_NOW,
    )
    assert count == 2
    assert len(background.tasks) == 2
    first = background.tasks[0]
    assert first.func is deliver_webhook
    assert first.args[0] == "https://a.example.com/h"
    assert first.args[1] == "s1"
    assert cast("WebhookDelivery", first.args[2]).event == "ticket.case_decided"


@pytest.mark.asyncio
async def test_deliver_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("network down")

    monkeypatch.setattr(dispatcher_module, "build_resilient_client", _boom)
    delivery = build_delivery(_ticket(), WebhookEvent.CASE_DECIDED, now=_NOW)
    # Не должно бросить (фоновый таск никогда не роняет процесс).
    await deliver_webhook("https://x.example.com/h", "secret-value-1234", delivery, get_settings())
