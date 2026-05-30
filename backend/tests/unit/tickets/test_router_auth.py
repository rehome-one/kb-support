"""Unit-тест fail-closed seam аутентификации (без БД).

Без переопределения `get_current_principal` зависимость отдаёт 401 (problem+json).
Запрос до БД не доходит — поэтому тест не требует Postgres.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from api.main import app


def test_get_without_auth_returns_401_problem_json() -> None:
    with TestClient(app) as client:
        resp = client.get(f"/api/v1/support/tickets/{uuid.uuid4()}")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 401
    assert body["title"] == "Unauthorized"
    assert body["type"].endswith("/unauthorized")


def test_post_without_auth_returns_401() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/support/tickets",
            json={"subject": "x", "type": "PAYMENT"},
        )
    assert resp.status_code == 401
