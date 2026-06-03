"""Prometheus-метрики SLA (E4-7 #91): breach, TTFR, TTR.

Отдельный неймспейс `sla_*` (эталон — `clients/metrics.py`). Регистрируются в
дефолтном реестре prometheus_client → попадают в существующий `/metrics`. Запись
синхронно на событиях (первый ответ / решение) — без воркера. Лейблы низкой
кардинальности (`type`/`priority`/`team`/`kind`) — без ПДн (ticket_id/requester_id
НЕ используются). Квантили p50/p95/p99 — на стороне Prometheus (`histogram_quantile`).

Запись идёт ВНУТРИ транзакции до commit (как в #70): откат БД метрику не отменит —
допустимый компромисс синхронной in-transaction записи (вероятность отката низкая).
Граница breach — включительно (`>=`), согласовано с `sla_state.is_resolution_breached`.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from api.tickets.models import Ticket

_KIND_FIRST_RESPONSE = "first_response"
_KIND_RESOLUTION = "resolution"

# Бакеты под длительности SLA (сек): от 1 мин до 7 дней (TTFR — минуты…часы,
# TTR — часы…дни).
_SLA_BUCKETS = (
    60,
    300,
    900,
    1800,
    3600,
    7200,
    14400,
    28800,
    86400,
    172800,
    432000,
    604800,
)

SLA_BREACHES = Counter(
    "sla_breaches_total",
    "Нарушения SLA (kind: first_response | resolution)",
    ["type", "priority", "team", "kind"],
)
SLA_TTFR = Histogram(
    "sla_time_to_first_response_seconds",
    "Время до первого публичного ответа оператора (сек)",
    ["type", "priority", "team"],
    buckets=_SLA_BUCKETS,
)
SLA_TTR = Histogram(
    "sla_time_to_resolution_seconds",
    "Время до решения за вычетом пауз — business time (сек)",
    ["type", "priority", "team"],
    buckets=_SLA_BUCKETS,
)


def _labels(ticket: Ticket) -> dict[str, str]:
    """Лейблы низкой кардинальности из заявки (team отсутствует → «none»)."""
    return {
        "type": ticket.type,
        "priority": ticket.priority,
        "team": ticket.team or "none",
    }


def record_first_response(ticket: Ticket) -> None:
    """Записать TTFR и first-response breach при первом публичном ответе оператора.

    Вызывать после установки `first_responded_at` (#89). TTFR — wall-clock (первый
    ответ паузами не двигается). Breach — только при наличии дедлайна и просрочке.
    """
    labels = _labels(ticket)
    if ticket.first_responded_at is not None:
        ttfr = (ticket.first_responded_at - ticket.created_at).total_seconds()
        SLA_TTFR.labels(**labels).observe(max(0.0, ttfr))
    if (
        ticket.first_response_due_at is not None
        and ticket.first_responded_at is not None
        and ticket.first_responded_at >= ticket.first_response_due_at
    ):
        SLA_BREACHES.labels(**labels, kind=_KIND_FIRST_RESPONSE).inc()


def record_resolution(ticket: Ticket) -> None:
    """Записать TTR (business time) и resolution breach при решении заявки.

    Вызывать ОДИН раз — на ПЕРВОМ переходе в RESOLVED (caller гейтит, чтобы повторное
    решение после REOPENED не задваивало TTR/breach). pause-accounting уже отработал →
    `sla_paused_seconds` финален. TTR = (resolved_at − created_at) − паузы. Breach —
    только при наличии дедлайна и просрочке (дедлайн уже сдвинут паузами, #88).
    """
    labels = _labels(ticket)
    if ticket.resolved_at is not None:
        wall = (ticket.resolved_at - ticket.created_at).total_seconds()
        SLA_TTR.labels(**labels).observe(max(0.0, wall - ticket.sla_paused_seconds))
    if (
        ticket.resolution_due_at is not None
        and ticket.resolved_at is not None
        and ticket.resolved_at >= ticket.resolution_due_at
    ):
        SLA_BREACHES.labels(**labels, kind=_KIND_RESOLUTION).inc()
