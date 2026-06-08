"""Prometheus-метрика оценок качества (E9-1, #183, FR-8.2/ADR-0012 D4).

Распределение выставленных оценок `ticket_ratings_total{rating}` — для Grafana-rate
(низкие/высокие оценки во времени). Эталон — `analytics/metrics.py` (#168),
`tickets/sla_metrics.py` (#91): Counter в дефолтном реестре prometheus_client →
существующий `/metrics`.

**ФЗ-152 (ADR-0012 D6):** label — ТОЛЬКО число оценки (1-5, низкая кардинальность);
`rating_comment` (свободный текст, потенц. ПДн) сюда НЕ попадает. avg/распределение в
аналитике (`quality_stats` #165, satisfaction #167) — отдельный контур, не дублируем.

Инкремент синхронно в `actions.rate()` (как #168) — это счётчик СОБЫТИЙ оценки: повторная
оценка (overwrite, ADR-0012 D5) даёт +1, поэтому метрика отражает rate выставлений, НЕ
число уникально оценённых заявок.
"""

from __future__ import annotations

from prometheus_client import Counter

TICKET_RATINGS = Counter(
    "ticket_ratings_total",
    "Выставленные оценки заявителей (распределение по баллу, FR-8.2)",
    ["rating"],
)


def record_rating(rating: int) -> None:
    """Инкремент `ticket_ratings_total{rating}`. Label — только балл (1-5), без ПДн."""
    TICKET_RATINGS.labels(rating=str(rating)).inc()
