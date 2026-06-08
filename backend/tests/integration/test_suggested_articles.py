"""Integration-тест GET /tickets/{id}/suggested-articles (E6-6 #130) — Postgres.

Покрывает: operator-only (заявитель→403, чужая/нет→404); config-gated (kb-search off →
degraded=true, []); override клиента → degraded=false со статьями. Принципалы и kb-search —
через `app.dependency_overrides`.
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
from api.clients.kb_search import ArticleSuggestion
from api.clients.kb_search.deps import get_kb_search_client
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="suggested-articles требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

_OPERATOR = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)
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
    app.dependency_overrides.pop(get_kb_search_client, None)
    asyncio.run(engine.dispose())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _create_ticket(client: TestClient) -> str:
    resp = client.post("/api/v1/support/tickets", json={"subject": "оплата", "type": "PAYMENT"})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


def test_degraded_when_kb_search_off(client: TestClient) -> None:
    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/suggested-articles")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["degraded"] is True  # пустой kb_search_api_token → выключено
    assert data["articles"] == []


def test_articles_when_client_overridden(client: TestClient) -> None:
    class _FakeKbSearch:
        async def suggest_articles(self, query: str) -> list[ArticleSuggestion]:
            return [ArticleSuggestion(slug="help/a", title="A", url=None)]

    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    app.dependency_overrides[get_kb_search_client] = lambda: _FakeKbSearch()
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/suggested-articles")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["degraded"] is False
    assert [a["slug"] for a in data["articles"]] == ["help/a"]


def test_requester_owner_forbidden_and_missing_404(client: TestClient) -> None:
    # Заявитель создаёт СВОЮ заявку (requester_id=его), затем GET → проходит видимость,
    # но operator-only → 403 (ПДн БЗ-подсказок не для заявителя).
    _use(_REQUESTER)
    own = client.post("/api/v1/support/tickets", json={"subject": "своя", "type": "PAYMENT"})
    assert own.status_code == 201, own.text
    own_id = own.json()["data"]["id"]
    assert client.get(f"/api/v1/support/tickets/{own_id}/suggested-articles").status_code == 403
    # Несуществующая заявка для оператора → 404 (anti-enum).
    _use(_OPERATOR)
    assert (
        client.get(f"/api/v1/support/tickets/{uuid.uuid4()}/suggested-articles").status_code == 404
    )
