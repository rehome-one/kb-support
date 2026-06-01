"""Тесты клиентских метрик (E3-2): инкремент + экспорт в /metrics."""

from __future__ import annotations

from prometheus_client import REGISTRY

from api.clients.metrics import record_request
from api.observability.metrics import metrics_response


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_record_request_increments_counter_and_histogram() -> None:
    labels = {"client": "svc", "operation": "op", "outcome": "success"}
    before = _sample("external_client_requests_total", labels)
    before_count = _sample(
        "external_client_request_duration_seconds_count", {"client": "svc", "operation": "op"}
    )

    record_request("svc", "op", "success", 0.02)

    assert _sample("external_client_requests_total", labels) == before + 1
    assert (
        _sample(
            "external_client_request_duration_seconds_count",
            {"client": "svc", "operation": "op"},
        )
        == before_count + 1
    )


def test_metrics_endpoint_exposes_client_series() -> None:
    record_request("svc", "op", "error", 0.05)
    body = bytes(metrics_response().body).decode()
    assert "external_client_requests_total" in body
    assert "external_client_request_duration_seconds" in body
