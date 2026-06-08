"""Unit-тесты метрики оценок (E9-1, #183). Дефолтный REGISTRY (паттерн #168/#91)."""

from __future__ import annotations

from prometheus_client import REGISTRY

from api.tickets.rating_metrics import record_rating


def _count(rating: int) -> float:
    value = REGISTRY.get_sample_value("ticket_ratings_total", {"rating": str(rating)})
    return value or 0.0


def test_record_increments_labelled_counter() -> None:
    before = _count(1)
    record_rating(1)
    assert _count(1) == before + 1


def test_labels_independent_by_rating() -> None:
    before_2 = _count(2)
    before_5 = _count(5)
    record_rating(2)
    assert _count(2) == before_2 + 1
    assert _count(5) == before_5  # инкремент одного балла не трогает другой
