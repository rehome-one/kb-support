"""Unit-тесты метрики rate входящих заявок (E8-4, #168). Дефолтный REGISTRY (паттерн #91)."""

from __future__ import annotations

from prometheus_client import REGISTRY

from api.analytics.metrics import record_ticket_created
from api.tickets.models import Ticket


def _count(ticket_type: str, channel: str) -> float:
    value = REGISTRY.get_sample_value(
        "tickets_created_total", {"type": ticket_type, "channel": channel}
    )
    return value or 0.0


def test_record_increments_labelled_counter() -> None:
    before = _count("PAYMENT", "EMAIL")
    record_ticket_created(Ticket(type="PAYMENT", channel="EMAIL"))
    assert _count("PAYMENT", "EMAIL") == before + 1


def test_labels_are_independent_by_type_and_channel() -> None:
    before_ai = _count("OTHER", "AI_CHAT")
    before_web = _count("OTHER", "WEB_FORM")
    record_ticket_created(Ticket(type="OTHER", channel="AI_CHAT"))
    # Инкремент одного лейбла не трогает другой канал.
    assert _count("OTHER", "AI_CHAT") == before_ai + 1
    assert _count("OTHER", "WEB_FORM") == before_web
