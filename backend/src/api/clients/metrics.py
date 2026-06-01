"""Prometheus-метрики HTTP-клиентов к соседям (E3-2, AT-003).

Отдельный неймспейс `external_client_*` — не путать с метриками HTTP-сервера
(`observability/metrics.py`). Регистрируются в дефолтном реестре prometheus_client
→ попадают в существующий `/metrics`. Лейблы низкой кардинальности
(`client`, `operation`, `outcome`) — без значений ПДн.

Квантили p50/p95/p99 считаются на стороне Prometheus через `histogram_quantile`
по бакетам (Histogram, не Summary — агрегируется между инстансами).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# Бакеты под сетевые задержки вызовов соседей (сек): от 5 мс до 10 с.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

CLIENT_REQUESTS = Counter(
    "external_client_requests_total",
    "Вызовы внешних сервисов из kb-support",
    ["client", "operation", "outcome"],
)
CLIENT_DURATION = Histogram(
    "external_client_request_duration_seconds",
    "Длительность вызова внешнего сервиса (сек)",
    ["client", "operation"],
    buckets=_LATENCY_BUCKETS,
)


def record_request(client: str, operation: str, outcome: str, elapsed: float) -> None:
    """Учесть исход (`success`/`error`/`circuit_open`) и длительность вызова."""
    CLIENT_REQUESTS.labels(client=client, operation=operation, outcome=outcome).inc()
    CLIENT_DURATION.labels(client=client, operation=operation).observe(elapsed)
