"""Контрактные smoke-тесты: реализация ↔ docs/openapi.yaml (AT-002, #4)."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from tests.contract.conftest import (
    SPEC,
    assert_response_conforms,
    requires_postgres,
)


def test_spec_loads_and_has_core_paths() -> None:
    """Sanity: production-spec загружается и содержит ключевые пути/схемы."""
    assert SPEC["openapi"].startswith("3.1")
    assert "/api/v1/support/tickets" in SPEC["paths"]
    assert "/api/v1/support/tickets/{id}" in SPEC["paths"]
    for schema in ("Ticket", "TicketSummary", "Pagination", "ResponseEnvelope"):
        assert schema in SPEC["components"]["schemas"]


@requires_postgres
def test_list_tickets_response_conforms(operator_client: TestClient) -> None:
    """Drift-детектор: реальный ответ GET /tickets соответствует контракту."""
    # Создаём заявку, чтобы в data был ≥1 элемент → валидируется схема TicketSummary.
    created = operator_client.post(
        "/api/v1/support/tickets", json={"subject": "contract", "type": "PAYMENT"}
    )
    assert created.status_code == 201

    resp = operator_client.get("/api/v1/support/tickets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"], "ожидался непустой список для валидации TicketSummary"
    assert_response_conforms("/api/v1/support/tickets", "get", "200", body)


@requires_postgres
def test_create_ticket_response_conforms(operator_client: TestClient) -> None:
    """Drift-детектор: реальный ответ POST /tickets (201) соответствует Ticket."""
    resp = operator_client.post(
        "/api/v1/support/tickets", json={"subject": "contract", "type": "MAINTENANCE"}
    )
    assert resp.status_code == 201
    assert_response_conforms("/api/v1/support/tickets", "post", "201", resp.json())


@requires_postgres
def test_ticket_history_response_conforms(operator_client: TestClient) -> None:
    """Drift-детектор: реальный ответ GET /{id}/history соответствует TicketHistory."""
    # Создание заявки пишет неизменяемую строку журнала `created` → history непуст,
    # что позволяет провалидировать элемент TicketHistory (включая from_value: null).
    created = operator_client.post(
        "/api/v1/support/tickets", json={"subject": "history", "type": "PAYMENT"}
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["id"]

    resp = operator_client.get(f"/api/v1/support/tickets/{ticket_id}/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"], "ожидалась ≥1 строка журнала (created) для валидации TicketHistory"
    assert_response_conforms("/api/v1/support/tickets/{id}/history", "get", "200", body)


def test_prism_mock_serves_tickets(prism_mock: str) -> None:
    """Опционально (RUN_PRISM_CONTRACT=1): Prism mock из спеки отдаёт валидный ответ."""
    resp = httpx.get(
        f"{prism_mock}/api/v1/support/tickets",
        headers={"Authorization": "Bearer contract-test"},
        timeout=30,
    )
    assert resp.status_code == 200
    assert_response_conforms("/api/v1/support/tickets", "get", "200", resp.json())
