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


def test_requester_context_gated_response_conforms(operator_client: TestClient) -> None:
    """AT-002: ответ requester-context (gated, секции null) соответствует RequesterContext."""
    created = operator_client.post(
        "/api/v1/support/tickets", json={"subject": "ctx", "type": "PAYMENT"}
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["id"]

    resp = operator_client.get(f"/api/v1/support/tickets/{ticket_id}/requester-context")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["degraded"] is True  # пустой токен → интеграция выключена
    assert_response_conforms(
        "/api/v1/support/tickets/{id}/requester-context", "get", "200", resp.json()
    )


def test_requester_context_populated_response_conforms(operator_client: TestClient) -> None:
    """AT-002: НАПОЛНЕННЫЙ ответ (все секции) соответствует RequesterContext — ловит дрейф
    маппинга DTO → схема (override platform-клиента, без сети)."""
    import datetime

    from api.clients.platform import Booking, Collaborator, Contact, Premises, UserProfile
    from api.main import app
    from api.tickets.requester_context import get_platform_client

    premises_id = uuid.uuid4()

    class _FullClient:
        async def get_user(self, user_id: uuid.UUID) -> UserProfile:
            return UserProfile(
                id=user_id,
                display_name="Заявитель",
                email="a@b.com",
                phone="+7",
                role="tenant",
                is_active=True,
                created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            )

        async def get_premises(self, premises_id: uuid.UUID) -> Premises:
            return Premises(
                id=premises_id,
                address="СПб",
                kind="apartment",
                rooms=2,
                area_m2=54.0,
                landlord_id=uuid.uuid4(),
            )

        async def get_booking(self, booking_id: uuid.UUID) -> Booking:
            return Booking(
                id=booking_id,
                premises_id=premises_id,
                tenant_id=uuid.uuid4(),
                landlord_id=uuid.uuid4(),
                status="active",
                period_start=datetime.date(2026, 1, 1),
                period_end=None,
                monthly_rent=50000.0,
            )

        async def get_collaborator(self, collaborator_id: uuid.UUID) -> Collaborator:
            return Collaborator(
                id=collaborator_id,
                name="Клининг",
                category="cleaning",
                contact=Contact(email="c@d.com", phone=None),
                is_active=True,
            )

    # Без requester_id оператор сам заявитель → заявка ему видна; premises/booking
    # заданы, чтобы наполнить соответствующие секции.
    created = operator_client.post(
        "/api/v1/support/tickets",
        json={
            "subject": "ctx-full",
            "type": "PAYMENT",
            "premises_id": str(premises_id),
            "booking_id": str(uuid.uuid4()),
        },
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["id"]

    app.dependency_overrides[get_platform_client] = lambda: _FullClient()
    try:
        resp = operator_client.get(f"/api/v1/support/tickets/{ticket_id}/requester-context")
    finally:
        app.dependency_overrides.pop(get_platform_client, None)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["degraded"] is False
    assert data["user"]["display_name"] == "Заявитель"
    assert data["premises"]["address"] == "СПб"
    assert_response_conforms(
        "/api/v1/support/tickets/{id}/requester-context", "get", "200", resp.json()
    )


@requires_postgres
def test_business_hours_responses_conform(admin_client: TestClient) -> None:
    """AT-002: create/get/list business-hours соответствуют схеме BusinessHours (#86)."""
    create = admin_client.post(
        "/api/v1/support/business-hours",
        json={
            "name": "contract",
            "timezone": "Europe/Moscow",
            "schedule": {"mon": [["09:00", "18:00"]]},
        },
    )
    assert create.status_code == 201, create.text
    assert_response_conforms("/api/v1/support/business-hours", "post", "201", create.json())
    bh_id = create.json()["data"]["id"]

    got = admin_client.get(f"/api/v1/support/business-hours/{bh_id}")
    assert got.status_code == 200
    assert_response_conforms("/api/v1/support/business-hours/{id}", "get", "200", got.json())

    patched = admin_client.patch(
        f"/api/v1/support/business-hours/{bh_id}", json={"is_active": False}
    )
    assert patched.status_code == 200
    assert_response_conforms("/api/v1/support/business-hours/{id}", "patch", "200", patched.json())

    listed = admin_client.get("/api/v1/support/business-hours")
    assert listed.status_code == 200
    assert_response_conforms("/api/v1/support/business-hours", "get", "200", listed.json())

    # Пустой дефолт schedule={} тоже должен конформить BusinessHours (drift пустых веток).
    empty = admin_client.post(
        "/api/v1/support/business-hours", json={"name": "empty", "timezone": "UTC"}
    )
    assert empty.status_code == 201
    assert empty.json()["data"]["schedule"] == {}
    assert_response_conforms("/api/v1/support/business-hours", "post", "201", empty.json())


@requires_postgres
def test_sla_policy_responses_conform(admin_client: TestClient) -> None:
    """AT-002: create/get/update/list sla-policies соответствуют схеме SLAPolicy (#86)."""
    create = admin_client.post(
        "/api/v1/support/sla-policies",
        json={
            "name": "contract policy",
            "applies_to": {"types": ["PAYMENT"]},
            "first_response_minutes": 30,
            "resolution_minutes": 240,
            "priority": 5,
        },
    )
    assert create.status_code == 201, create.text
    assert_response_conforms("/api/v1/support/sla-policies", "post", "201", create.json())
    policy_id = create.json()["data"]["id"]

    got = admin_client.get(f"/api/v1/support/sla-policies/{policy_id}")
    assert got.status_code == 200
    assert_response_conforms("/api/v1/support/sla-policies/{id}", "get", "200", got.json())

    patched = admin_client.patch(f"/api/v1/support/sla-policies/{policy_id}", json={"priority": 7})
    assert patched.status_code == 200
    assert_response_conforms("/api/v1/support/sla-policies/{id}", "patch", "200", patched.json())

    listed = admin_client.get("/api/v1/support/sla-policies")
    assert listed.status_code == 200
    assert_response_conforms("/api/v1/support/sla-policies", "get", "200", listed.json())

    # Дефолтный applies_to ({}) тоже должен конформить SLAPolicy/SLAAppliesTo.
    minimal = admin_client.post(
        "/api/v1/support/sla-policies",
        json={"name": "minimal", "first_response_minutes": 60, "resolution_minutes": 480},
    )
    assert minimal.status_code == 201
    assert minimal.json()["data"]["applies_to"] == {}
    assert_response_conforms("/api/v1/support/sla-policies", "post", "201", minimal.json())


@requires_postgres
def test_automation_rule_responses_conform(admin_client: TestClient) -> None:
    """AT-002: create/get/patch/list automation-rules соответствуют AutomationRule (#104).

    Правило несёт несколько типов действий → валидирует дискриминированный union
    AutomationAction (oneOf) в ответе."""
    create = admin_client.post(
        "/api/v1/support/automation-rules",
        json={
            "name": "contract rule",
            "trigger": "on_create",
            "conditions": {
                "types": ["FRAUD"],
                "priorities": ["critical"],
                "channels": ["AI_CHAT"],
                "keywords": ["fraud"],
            },
            "actions": [
                {"action": "set_priority", "params": {"priority": "critical"}},
                {"action": "assign", "params": {"strategy": "least_load", "team": "legal"}},
                {"action": "escalate", "params": {}},
                {"action": "add_tag", "params": {"tags": ["auto"]}},
                {"action": "notify", "params": {"recipient": "supervisor"}},
            ],
            "order": 3,
        },
    )
    assert create.status_code == 201, create.text
    assert_response_conforms("/api/v1/support/automation-rules", "post", "201", create.json())
    rule_id = create.json()["data"]["id"]

    got = admin_client.get(f"/api/v1/support/automation-rules/{rule_id}")
    assert got.status_code == 200
    assert_response_conforms("/api/v1/support/automation-rules/{id}", "get", "200", got.json())

    patched = admin_client.patch(f"/api/v1/support/automation-rules/{rule_id}", json={"order": 8})
    assert patched.status_code == 200
    assert_response_conforms(
        "/api/v1/support/automation-rules/{id}", "patch", "200", patched.json()
    )

    listed = admin_client.get("/api/v1/support/automation-rules")
    assert listed.status_code == 200
    assert_response_conforms("/api/v1/support/automation-rules", "get", "200", listed.json())


def test_time_based_rule_conditions_conform(admin_client: TestClient) -> None:
    """AT-002 (#110): time_based-правило с новыми полями conditions (statuses/inactive_minutes/
    unanswered_minutes) принимается и конформит AutomationRule."""
    create = admin_client.post(
        "/api/v1/support/automation-rules",
        json={
            "name": "time-based contract rule",
            "trigger": "time_based",
            "conditions": {
                "statuses": ["PENDING"],
                "inactive_minutes": 4320,
                "unanswered_minutes": 60,
            },
            "actions": [{"action": "set_status", "params": {"status": "CLOSED"}}],
        },
    )
    assert create.status_code == 201, create.text
    assert_response_conforms("/api/v1/support/automation-rules", "post", "201", create.json())
    body = create.json()["data"]
    assert body["conditions"]["statuses"] == ["PENDING"]
    assert body["conditions"]["inactive_minutes"] == 4320

    rule_id = body["id"]
    got = admin_client.get(f"/api/v1/support/automation-rules/{rule_id}")
    assert got.status_code == 200
    assert_response_conforms("/api/v1/support/automation-rules/{id}", "get", "200", got.json())


def test_time_field_rejected_on_non_time_based_trigger(admin_client: TestClient) -> None:
    """#110 footgun: временные поля на trigger≠time_based → 422 (валидатор схемы)."""
    resp = admin_client.post(
        "/api/v1/support/automation-rules",
        json={
            "name": "bad rule",
            "trigger": "on_create",
            "conditions": {"inactive_minutes": 60},
            "actions": [{"action": "add_tag", "params": {"tags": ["x"]}}],
        },
    )
    assert resp.status_code == 422, resp.text


@requires_postgres
def test_ticket_exposes_sla_state(operator_client: TestClient) -> None:
    """AT-002 (#89): ответ getTicket несёт sla_state из домена SlaState и конформен."""
    created = operator_client.post(
        "/api/v1/support/tickets", json={"subject": "sla", "type": "PAYMENT"}
    )
    assert created.status_code == 201
    ticket_id = created.json()["data"]["id"]

    resp = operator_client.get(f"/api/v1/support/tickets/{ticket_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["sla_state"] in {"none", "ok", "approaching", "breached"}
    # Источники расчёта (sla_paused_at) НЕ должны утекать в ответ (Field exclude).
    assert "sla_paused_at" not in body["data"]
    assert_response_conforms("/api/v1/support/tickets/{id}", "get", "200", body)


def test_prism_mock_serves_tickets(prism_mock: str) -> None:
    """Опционально (RUN_PRISM_CONTRACT=1): Prism mock из спеки отдаёт валидный ответ."""
    resp = httpx.get(
        f"{prism_mock}/api/v1/support/tickets",
        headers={"Authorization": "Bearer contract-test"},
        timeout=30,
    )
    assert resp.status_code == 200
    assert_response_conforms("/api/v1/support/tickets", "get", "200", resp.json())
