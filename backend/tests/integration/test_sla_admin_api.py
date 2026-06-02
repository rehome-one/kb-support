"""Integration-тесты admin CRUD SLA-конфигурации (#86) — требуют Postgres.

Покрывают: полный CRUD `business-hours` и `sla-policies`; admin-гейт (security —
не-админ → 403 на чтении И записи); 404 на несуществующий id; 422 на битом теле и
на ссылке `business_hours_id` без записи (детерминированно, не 500).

Принципал инжектится через `app.dependency_overrides` (seam #6). Запускается в CI
(service container) и локально при `POSTGRES_AVAILABLE=1`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.auth.scopes import STAFF_ADMIN_SCOPE
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Admin CRUD SLA требует живой Postgres (CI service container / POSTGRES_AVAILABLE=1).",
)

_ADMIN = Principal(
    user_id=uuid.uuid4(),
    kind=PrincipalKind.OPERATOR,
    scopes=frozenset({STAFF_ADMIN_SCOPE}),
    teams=frozenset({TicketTeam.SUPPORT}),
)
_OPERATOR = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR)
_REQUESTER = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER)


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture(autouse=True)
def _override_db_session() -> Iterator[None]:
    """get_session → NullPool-движок (свежее соединение на текущем loop, см. #85)."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_test_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _get_test_session
    yield
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_principal, None)
    asyncio.run(engine.dispose())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# --- BusinessHours CRUD ---


def test_business_hours_crud_cycle(client: TestClient) -> None:
    _use(_ADMIN)
    create = client.post(
        "/api/v1/support/business-hours",
        json={
            "name": "РФ будни",
            "timezone": "Europe/Moscow",
            "schedule": {"mon": [["09:00", "18:00"]], "sat": []},
        },
    )
    assert create.status_code == 201, create.text
    bh = create.json()["data"]
    bh_id = bh["id"]
    assert bh["is_active"] is True
    assert bh["schedule"]["mon"] == [["09:00", "18:00"]]

    got = client.get(f"/api/v1/support/business-hours/{bh_id}")
    assert got.status_code == 200
    assert got.json()["data"]["timezone"] == "Europe/Moscow"

    listed = client.get("/api/v1/support/business-hours")
    assert listed.status_code == 200
    assert any(item["id"] == bh_id for item in listed.json()["data"])

    patched = client.patch(
        f"/api/v1/support/business-hours/{bh_id}",
        json={"is_active": False, "timezone": "Asia/Yekaterinburg"},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["is_active"] is False
    assert patched.json()["data"]["timezone"] == "Asia/Yekaterinburg"


def test_business_hours_not_found(client: TestClient) -> None:
    _use(_ADMIN)
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/support/business-hours/{missing}").status_code == 404
    assert (
        client.patch(f"/api/v1/support/business-hours/{missing}", json={"name": "x"}).status_code
        == 404
    )


def test_business_hours_invalid_body_422(client: TestClient) -> None:
    _use(_ADMIN)
    resp = client.post(
        "/api/v1/support/business-hours",
        json={
            "name": "bad",
            "timezone": "Europe/Moscow",
            "schedule": {"mon": [["18:00", "09:00"]]},
        },
    )
    assert resp.status_code == 422


# --- SLAPolicy CRUD ---


def test_sla_policy_crud_cycle(client: TestClient) -> None:
    _use(_ADMIN)
    bh = client.post(
        "/api/v1/support/business-hours",
        json={"name": "график для политики", "timezone": "Europe/Moscow", "schedule": {}},
    ).json()["data"]

    create = client.post(
        "/api/v1/support/sla-policies",
        json={
            "name": "Критичные платежи",
            "applies_to": {"types": ["PAYMENT"], "priorities": ["critical"]},
            "first_response_minutes": 30,
            "resolution_minutes": 240,
            "business_hours_id": bh["id"],
            "priority": 10,
        },
    )
    assert create.status_code == 201, create.text
    policy = create.json()["data"]
    policy_id = policy["id"]
    assert policy["is_active"] is True
    assert policy["applies_to"] == {"types": ["PAYMENT"], "priorities": ["critical"]}
    assert policy["business_hours_id"] == bh["id"]

    got = client.get(f"/api/v1/support/sla-policies/{policy_id}")
    assert got.status_code == 200

    listed = client.get("/api/v1/support/sla-policies")
    assert listed.status_code == 200
    assert any(item["id"] == policy_id for item in listed.json()["data"])

    # PATCH №1: имя/условия/минуты (покрывает все ветки маппинга обновления).
    repatched = client.patch(
        f"/api/v1/support/sla-policies/{policy_id}",
        json={
            "name": "Переименовано",
            "applies_to": {"types": ["CONTRACT"]},
            "first_response_minutes": 45,
            "resolution_minutes": 300,
        },
    )
    assert repatched.status_code == 200
    rdata = repatched.json()["data"]
    assert rdata["name"] == "Переименовано"
    assert rdata["applies_to"] == {"types": ["CONTRACT"]}
    assert rdata["first_response_minutes"] == 45
    assert rdata["resolution_minutes"] == 300

    # PATCH №2: занулить график (24/7) + деактивировать.
    patched = client.patch(
        f"/api/v1/support/sla-policies/{policy_id}",
        json={"business_hours_id": None, "is_active": False, "priority": 1},
    )
    assert patched.status_code == 200
    data = patched.json()["data"]
    assert data["business_hours_id"] is None
    assert data["is_active"] is False
    assert data["priority"] == 1


def test_request_id_echoed_from_header(client: TestClient) -> None:
    """Валидный X-Request-Id возвращается в конверте; битый — заменяется на новый uuid."""
    _use(_ADMIN)
    rid = str(uuid.uuid4())
    valid = client.post(
        "/api/v1/support/business-hours",
        json={"name": "rid", "timezone": "UTC", "schedule": {}},
        headers={"X-Request-Id": rid},
    )
    assert valid.status_code == 201
    assert valid.json()["request_id"] == rid

    bad = client.get("/api/v1/support/sla-policies", headers={"X-Request-Id": "not-a-uuid"})
    assert bad.status_code == 200
    uuid.UUID(bad.json()["request_id"])  # подставлен валидный uuid


def test_sla_policy_not_found(client: TestClient) -> None:
    _use(_ADMIN)
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/support/sla-policies/{missing}").status_code == 404
    assert (
        client.patch(f"/api/v1/support/sla-policies/{missing}", json={"priority": 1}).status_code
        == 404
    )


def test_sla_policy_nonexistent_business_hours_422_not_500(client: TestClient) -> None:
    """Ссылка на несуществующий график → детерминированный 422 (pre-check), не 500 от FK."""
    _use(_ADMIN)
    resp = client.post(
        "/api/v1/support/sla-policies",
        json={
            "name": "битая ссылка",
            "first_response_minutes": 60,
            "resolution_minutes": 480,
            "business_hours_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 422, resp.text


def test_sla_policy_invalid_applies_to_422(client: TestClient) -> None:
    _use(_ADMIN)
    resp = client.post(
        "/api/v1/support/sla-policies",
        json={
            "name": "битый тип",
            "applies_to": {"types": ["NOT_A_TYPE"]},
            "first_response_minutes": 60,
            "resolution_minutes": 480,
        },
    )
    assert resp.status_code == 422


# --- Admin-гейт (security, правило 9): чтение И запись только админу ---


@pytest.mark.parametrize("principal", [_OPERATOR, _REQUESTER], ids=["operator", "requester"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/v1/support/business-hours", None),
        ("post", "/api/v1/support/business-hours", {"name": "x", "timezone": "UTC"}),
        ("get", "/api/v1/support/business-hours/{id}", None),
        ("patch", "/api/v1/support/business-hours/{id}", {"name": "x"}),
        ("get", "/api/v1/support/sla-policies", None),
        (
            "post",
            "/api/v1/support/sla-policies",
            {"name": "x", "first_response_minutes": 60, "resolution_minutes": 480},
        ),
        ("get", "/api/v1/support/sla-policies/{id}", None),
        ("patch", "/api/v1/support/sla-policies/{id}", {"priority": 1}),
    ],
)
def test_non_admin_forbidden(
    client: TestClient, principal: Principal, method: str, path: str, body: dict[str, object] | None
) -> None:
    """Не-админ (оператор без скоупа / заявитель) → ровно 403 на любом методе SLA."""
    _use(principal)
    url = path.format(id=uuid.uuid4())
    resp = client.request(method, url, json=body)
    assert resp.status_code == 403, f"{method} {url} as {principal.kind}: {resp.status_code}"
