"""Prometheus-метрики аналитики (E8-4, #168): rate входящих заявок (FR-7.3).

Отдельный неймспейс `tickets_created_total` (эталон — `tickets/sla_metrics.py` #91,
`clients/metrics.py`). Регистрируется в дефолтном реестре prometheus_client → попадает в
существующий `/metrics`. Лейблы низкой кардинальности (`type`/`channel`) — без ПДн
(ticket_id/requester_id НЕ используются).

**Покрытие FR-7.3 (важно — без дублей):** «rate заявок» = эта метрика (#168); «время в
очереди» (created→first_responded) уже = `sla_time_to_first_response_seconds` (TTFR, #91) —
ОТДЕЛЬНУЮ `support_queue_time_seconds` НЕ вводим (был бы дубль того же интервала на том же
событии); breach-rate = `sla_breaches_total` (#91); containment AI-чата — у kb-search
(отдаётся в `/stats` через config-gated seam #166, знаменателя у нас нет).

Запись синхронно in-transaction на создании (как #91): откат БД метрику не отменит —
принятый компромисс. Для `create_from_chat` инкремент идёт ПОСЛЕ успешного flush в ветке
ново-созданной заявки (идемпотентный возврат existing / откат гонки инкремент НЕ получают).
"""

from __future__ import annotations

from prometheus_client import Counter

from api.tickets.models import Ticket

TICKETS_CREATED = Counter(
    "tickets_created_total",
    "Созданные заявки (rate входящих, FR-7.3)",
    ["type", "channel"],
)


def record_ticket_created(ticket: Ticket) -> None:
    """Инкремент `tickets_created_total{type,channel}` при создании заявки.

    Вызывать ровно на ново-созданной заявке (3 чокпоинта репозитория, рядом с `apply_sla`),
    НЕ на идемпотентном возврате существующей. Лейблы — доменные enum, без ПДн.
    """
    TICKETS_CREATED.labels(type=ticket.type, channel=ticket.channel).inc()
