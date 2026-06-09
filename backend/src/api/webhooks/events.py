"""Whitelist-конверт исходящих webhook-событий (E10-8 PR-B #198; ADR-0015 D5/D7).

Конверт БЕЗ ПДн/is_internal: только id/суммы (строкой — FR-9.8, деньги не считаем)/статусы,
как в карточке оператора. `decision_reason` НЕ включается (свободный текст — потенциальные ПДн).
`payout_released` несёт факт ВНУТРЕННЕГО решения PAID (D7), НЕ банковское подтверждение:
`payment_confirmed=false` пока `linked_payment_id` пуст (заполнится позже — inbound/#79).
"""

from __future__ import annotations

import datetime
import decimal
import json
import uuid
from dataclasses import dataclass
from typing import Any

from api.tickets.models import Ticket
from api.webhooks.enums import WebhookEvent


@dataclass(frozen=True)
class WebhookDelivery:
    """Готовая к доставке единица: событие, id доставки, timestamp подписи, сериализованное тело."""

    event: str
    delivery_id: uuid.UUID
    timestamp: int
    payload: bytes


def _amount(value: decimal.Decimal | None) -> str | None:
    """Сумма строкой (FR-9.8) или None — деньги не считаем, только переносим."""
    return str(value) if value is not None else None


def _data(ticket: Ticket, event: WebhookEvent) -> dict[str, Any]:
    """Whitelist полей события (без ПДн/is_internal/decision_reason)."""
    if event is WebhookEvent.CASE_DECIDED:
        return {
            "decision": ticket.decision,
            "approved_amount": _amount(ticket.approved_amount),
            "case_state": ticket.case_state,
        }
    if event is WebhookEvent.PAYOUT_RELEASED:
        return {
            "case_state": ticket.case_state,
            "approved_amount": _amount(ticket.approved_amount),
            "linked_payment_id": (
                str(ticket.linked_payment_id) if ticket.linked_payment_id else None
            ),
            # D7: до банковского подтверждения (linked_payment_id) — деньги ещё НЕ ушли.
            "payment_confirmed": ticket.linked_payment_id is not None,
        }
    return {}


def build_delivery(
    ticket: Ticket, event: WebhookEvent, *, now: datetime.datetime
) -> WebhookDelivery:
    """Собрать whitelist-конверт события и сериализовать детерминированно (для подписи)."""
    delivery_id = uuid.uuid4()
    envelope = {
        "event": event.value,
        "delivery_id": str(delivery_id),
        "occurred_at": now.isoformat(),
        "ticket_id": str(ticket.id),
        "ticket_number": ticket.number,
        "data": _data(ticket, event),
    }
    payload = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode()
    return WebhookDelivery(
        event=event.value,
        delivery_id=delivery_id,
        timestamp=int(now.timestamp()),
        payload=payload,
    )
