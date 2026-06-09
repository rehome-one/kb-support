"""Домен webhook-событий (E10-8 #198; контракт `docs/openapi.yaml` WebhookSubscription).

13 событий — дословно из enum контракта (`WebhookSubscription.events.items.enum`).
Хранятся `String` в JSONB-массиве подписки + валидация Python-энумом на границе API
(E1-конвенция, Issue #5 — без нативного PG ENUM). Claims-события (`case_decided`/
`payout_released`/`insurance_event`) эмитятся в PR-B; остальные — задел контракта.
"""

from __future__ import annotations

from enum import Enum


class WebhookEvent(str, Enum):
    """Имя webhook-события (значение = строка из контракта `ticket.*`)."""

    CREATED = "ticket.created"
    UPDATED = "ticket.updated"
    ASSIGNED = "ticket.assigned"
    ESCALATED = "ticket.escalated"
    RESOLVED = "ticket.resolved"
    CLOSED = "ticket.closed"
    REOPENED = "ticket.reopened"
    MESSAGE_ADDED = "ticket.message_added"
    SLA_BREACHED = "ticket.sla_breached"
    RATED = "ticket.rated"
    CASE_DECIDED = "ticket.case_decided"
    PAYOUT_RELEASED = "ticket.payout_released"
    INSURANCE_EVENT = "ticket.insurance_event"
