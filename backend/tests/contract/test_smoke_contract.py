"""Контрактные smoke-тесты: реализация ↔ docs/openapi.yaml (AT-002, #4)."""

from __future__ import annotations

import uuid

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
    assert "/api/v1/support/tickets/from-chat" in SPEC["paths"]
    for schema in ("Ticket", "TicketSummary", "Pagination", "ResponseEnvelope", "TicketFromChat"):
        assert schema in SPEC["components"]["schemas"]


@requires_postgres
def test_create_from_chat_response_conforms(service_client: TestClient) -> None:
    """Drift-детектор: ответ POST /from-chat (201) соответствует Ticket (E3-1, #69)."""
    resp = service_client.post(
        "/api/v1/support/tickets/from-chat",
        json={
            "chat_session_id": str(uuid.uuid4()),
            "requester_id": str(uuid.uuid4()),
            "transcript": [{"role": "user", "content": "контракт"}],
        },
    )
    assert resp.status_code == 201, resp.text
    assert_response_conforms("/api/v1/support/tickets/from-chat", "post", "201", resp.json())


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
def test_get_ticket_exposes_allowed_status_transitions(operator_client: TestClient) -> None:
    """getTicket отдаёт allowed_status_transitions (новое заявка NEW → OPEN/CLOSED)."""
    created = operator_client.post(
        "/api/v1/support/tickets", json={"subject": "transitions", "type": "PAYMENT"}
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["id"]

    resp = operator_client.get(f"/api/v1/support/tickets/{ticket_id}")
    assert resp.status_code == 200
    body = resp.json()
    # Явная проверка присутствия: поле optional + у Ticket нет additionalProperties:false,
    # поэтому conform сам по себе наличие не гарантирует.
    assert "allowed_status_transitions" in body["data"]
    assert body["data"]["allowed_status_transitions"] == ["OPEN", "CLOSED"]
    assert_response_conforms("/api/v1/support/tickets/{id}", "get", "200", body)


@requires_postgres
def test_assign_accepts_documented_body(operator_client: TestClient) -> None:
    """assign принимает задокументированное тело {assignee_id} и conform'ит Ticket."""
    created = operator_client.post(
        "/api/v1/support/tickets", json={"subject": "assign", "type": "PAYMENT"}
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["id"]

    assignee_id = "11111111-2222-3333-4444-555555555555"
    resp = operator_client.post(
        f"/api/v1/support/tickets/{ticket_id}/assign", json={"assignee_id": assignee_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["assignee_id"] == assignee_id
    assert_response_conforms("/api/v1/support/tickets/{id}/assign", "post", "200", body)


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
