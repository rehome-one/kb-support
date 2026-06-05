"""Integration-тесты CRUD шаблонов ответов (#126) — требуют Postgres.

Покрывают: CRUD `canned-responses`; RBAC (ADR-0009 Реш.4): CRUD — `staff_support`,
list/get — любой оператор, заявитель → 403; 404 на несуществующий id; type-фильтр; учёт
`type`-домена. Принципал инжектится через `app.dependency_overrides` (seam #6).
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
from api.auth.scopes import STAFF_SUPPORT_SCOPE
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="CRUD шаблонов требует живой Postgres (CI service container / POSTGRES_AVAILABLE=1).",
)

_SUPPORT = Principal(
    user_id=uuid.uuid4(),
    kind=PrincipalKind.OPERATOR,
    scopes=frozenset({STAFF_SUPPORT_SCOPE}),
    teams=frozenset({TicketTeam.SUPPORT}),
)
_OPERATOR = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR)
_REQUESTER = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER)


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


def test_crud_cycle(client: TestClient) -> None:
    _use(_SUPPORT)
    create = client.post(
        "/api/v1/support/canned-responses",
        json={
            "title": "Возврат средств",
            "body": "Здравствуйте, {{requester_name}}! По заявке {{ticket_number}}…",
            "type": "PAYMENT",
            "linked_article_slug": "help/refund",
        },
    )
    assert create.status_code == 201, create.text
    data = create.json()["data"]
    cid = data["id"]
    assert data["type"] == "PAYMENT"
    assert data["usage_count"] == 0
    assert data["linked_article_slug"] == "help/refund"

    # get/list доступны обычному оператору
    _use(_OPERATOR)
    got = client.get(f"/api/v1/support/canned-responses/{cid}")
    assert got.status_code == 200
    assert got.json()["data"]["title"] == "Возврат средств"

    listed = client.get("/api/v1/support/canned-responses")
    assert listed.status_code == 200
    assert any(item["id"] == cid for item in listed.json()["data"])

    # patch — снова под staff_support
    _use(_SUPPORT)
    patched = client.patch(
        f"/api/v1/support/canned-responses/{cid}",
        json={"title": "Возврат (обновлён)", "type": None},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["title"] == "Возврат (обновлён)"
    assert patched.json()["data"]["type"] is None  # type можно занулить


def test_type_filter(client: TestClient) -> None:
    _use(_SUPPORT)
    token = uuid.uuid4().hex
    client.post(
        "/api/v1/support/canned-responses",
        json={"title": f"fraud-{token}", "body": "b", "type": "FRAUD"},
    )
    client.post(
        "/api/v1/support/canned-responses",
        json={"title": f"payment-{token}", "body": "b", "type": "PAYMENT"},
    )
    _use(_OPERATOR)
    resp = client.get("/api/v1/support/canned-responses", params={"type": "FRAUD"})
    assert resp.status_code == 200
    titles = [c["title"] for c in resp.json()["data"] if token in c["title"]]
    assert titles == [f"fraud-{token}"]


def test_rbac_requester_forbidden_and_operator_cannot_write(client: TestClient) -> None:
    # Заявитель не видит шаблоны (operator-only на чтении).
    _use(_REQUESTER)
    assert client.get("/api/v1/support/canned-responses").status_code == 403
    # Обычный оператор без staff_support не может создавать/менять.
    _use(_OPERATOR)
    create = client.post("/api/v1/support/canned-responses", json={"title": "t", "body": "b"})
    assert create.status_code == 403


def test_not_found(client: TestClient) -> None:
    _use(_OPERATOR)
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/support/canned-responses/{missing}").status_code == 404
    _use(_SUPPORT)
    assert (
        client.patch(f"/api/v1/support/canned-responses/{missing}", json={"title": "x"}).status_code
        == 404
    )


def test_invalid_type_rejected(client: TestClient) -> None:
    _use(_SUPPORT)
    resp = client.post(
        "/api/v1/support/canned-responses",
        json={"title": "t", "body": "b", "type": "NOT_A_TYPE"},
    )
    assert resp.status_code == 422


# --- render-эндпоинт (#127) ---


def _create_ticket(client: TestClient) -> str:
    resp = client.post("/api/v1/support/tickets", json={"subject": "тема", "type": "OTHER"})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


def test_render_substitutes_local_vars_and_leaves_unavailable(client: TestClient) -> None:
    _use(_SUPPORT)
    canned = client.post(
        "/api/v1/support/canned-responses",
        json={
            "title": "t",
            "body": "Здравствуйте, {{requester_name}}! Заявка {{ticket_number}}.",
            "linked_article_slug": "help/x",
        },
    )
    cid = canned.json()["data"]["id"]

    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    rendered = client.post(
        f"/api/v1/support/canned-responses/{cid}/render", json={"ticket_id": ticket_id}
    )
    assert rendered.status_code == 200, rendered.text
    data = rendered.json()["data"]
    # ticket_number подставлен; requester_name остаётся плейсхолдером (platform off в тесте).
    assert "{{ticket_number}}" not in data["rendered_body"]
    assert "{{requester_name}}" in data["rendered_body"]
    assert data["linked_article_slug"] == "help/x"


def test_render_not_found(client: TestClient) -> None:
    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    # несуществующий шаблон → 404
    assert (
        client.post(
            f"/api/v1/support/canned-responses/{uuid.uuid4()}/render",
            json={"ticket_id": ticket_id},
        ).status_code
        == 404
    )
    # существующий шаблон, несуществующая заявка → 404
    _use(_SUPPORT)
    cid = client.post("/api/v1/support/canned-responses", json={"title": "t", "body": "b"}).json()[
        "data"
    ]["id"]
    _use(_OPERATOR)
    assert (
        client.post(
            f"/api/v1/support/canned-responses/{cid}/render",
            json={"ticket_id": str(uuid.uuid4())},
        ).status_code
        == 404
    )
