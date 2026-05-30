"""Unit tests на liveness probe `/healthz`."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    """`/healthz` всегда отвечает 200 OK с фиксированным body."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_response_model_validates(client: TestClient) -> None:
    """Response соответствует объявленной HealthzResponse Pydantic схеме —
    status fixed Literal['ok']. Дрейф схемы — провал теста."""
    resp = client.get("/healthz")
    body = resp.json()
    assert set(body.keys()) == {"status"}
    assert body["status"] == "ok"
