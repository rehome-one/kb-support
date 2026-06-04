"""Integration-тесты admin CRUD правил автоматизации (E5-2 #104) — требуют Postgres.

Покрывают: полный CRUD `automation-rules`; admin-гейт (security — не-админ → 403 на
чтении И записи, все 4 операции); 404 на несуществующий id (get/patch); 422 на битом
теле; round-trip `order`↔`apply_order` на уровне API (условие 2).

Принципал инжектится через `app.dependency_overrides` (seam #6). CI / POSTGRES_AVAILABLE.
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
    reason="Admin CRUD automation требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_ADMIN = Principal(
    user_id=uuid.uuid4(),
    kind=PrincipalKind.OPERATOR,
    scopes=frozenset({STAFF_ADMIN_SCOPE}),
    teams=frozenset({TicketTeam.SUPPORT}),
)
_OPERATOR = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR)
_REQUESTER = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER)

_VALID = {
    "name": "fraud-routing",
    "trigger": "on_create",
    "conditions": {"types": ["FRAUD"]},
    "actions": [{"action": "set_priority", "params": {"priority": "critical"}}],
    "order": 5,
}


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture(autouse=True)
def _override_db_session() -> Iterator[None]:
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


def test_crud_happy_path(client: TestClient) -> None:
    _use(_ADMIN)
    created = client.post("/api/v1/support/automation-rules", json=_VALID)
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    rule_id = data["id"]
    assert data["order"] == 5  # alias order↔apply_order на уровне API (условие 2)
    assert data["conditions"]["types"] == ["FRAUD"]
    assert data["actions"][0]["action"] == "set_priority"

    got = client.get(f"/api/v1/support/automation-rules/{rule_id}")
    assert got.status_code == 200
    assert got.json()["data"]["order"] == 5

    patched = client.patch(
        f"/api/v1/support/automation-rules/{rule_id}", json={"is_active": False, "order": 9}
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["is_active"] is False
    assert patched.json()["data"]["order"] == 9

    listed = client.get("/api/v1/support/automation-rules")
    assert listed.status_code == 200
    assert rule_id in {r["id"] for r in listed.json()["data"]}


@pytest.mark.parametrize("principal", [_OPERATOR, _REQUESTER])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/support/automation-rules", None),
        ("POST", "/api/v1/support/automation-rules", _VALID),
        ("GET", "/api/v1/support/automation-rules/{id}", None),
        ("PATCH", "/api/v1/support/automation-rules/{id}", {"is_active": False}),
    ],
)
def test_non_admin_forbidden(
    client: TestClient,
    principal: Principal,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    """Не-админ (оператор без скоупа / заявитель) → ровно 403 на любой операции."""
    _use(principal)
    url = path.format(id=uuid.uuid4())
    resp = client.request(method, url, json=body)
    assert resp.status_code == 403, f"{method} {url} as {principal.kind}: {resp.status_code}"


def test_get_unknown_returns_404(client: TestClient) -> None:
    _use(_ADMIN)
    resp = client.get(f"/api/v1/support/automation-rules/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_patch_unknown_returns_404(client: TestClient) -> None:
    _use(_ADMIN)
    resp = client.patch(
        f"/api/v1/support/automation-rules/{uuid.uuid4()}", json={"is_active": False}
    )
    assert resp.status_code == 404


def test_patch_replaces_trigger_conditions_actions(client: TestClient) -> None:
    _use(_ADMIN)
    created = client.post("/api/v1/support/automation-rules", json=_VALID)
    rule_id = created.json()["data"]["id"]

    patched = client.patch(
        f"/api/v1/support/automation-rules/{rule_id}",
        json={
            "trigger": "on_update",
            "conditions": {"channels": ["EMAIL"]},
            "actions": [{"action": "add_tag", "params": {"tags": ["reviewed"]}}],
        },
    )
    assert patched.status_code == 200, patched.text
    data = patched.json()["data"]
    assert data["trigger"] == "on_update"
    assert data["conditions"] == {"channels": ["EMAIL"]}
    assert data["actions"] == [{"action": "add_tag", "params": {"tags": ["reviewed"]}}]


def test_invalid_action_body_422(client: TestClient) -> None:
    _use(_ADMIN)
    # assign.direct без operator_id → cross-field 422 (не 500).
    bad = {
        **_VALID,
        "actions": [{"action": "assign", "params": {"strategy": "direct"}}],
    }
    resp = client.post("/api/v1/support/automation-rules", json=bad)
    assert resp.status_code == 422
