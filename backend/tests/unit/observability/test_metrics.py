"""Unit-тесты Prometheus-метрик и эндпоинта /metrics."""

from __future__ import annotations

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from api.main import app


def test_metrics_endpoint_exposes_series() -> None:
    with TestClient(app) as client:
        client.get("/healthz")
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text
    assert "http_request_duration_seconds" in resp.text


def test_request_counter_increments() -> None:
    labels = {"method": "GET", "endpoint": "/healthz", "status": "200"}
    with TestClient(app) as client:
        before = REGISTRY.get_sample_value("http_requests_total", labels) or 0.0
        client.get("/healthz")
        after = REGISTRY.get_sample_value("http_requests_total", labels) or 0.0
    assert after == before + 1


def test_endpoint_label_uses_route_template() -> None:
    """Антикардинальность: label endpoint — шаблон маршрута, не конкретный путь."""
    with TestClient(app) as client:
        client.get("/healthz")
        text = client.get("/metrics").text
    assert 'endpoint="/healthz"' in text
