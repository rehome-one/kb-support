"""Integration-тест учёта usage_count при ответе из шаблона (E6-4 #128) — Postgres.

Реальный flow: оператор создаёт заявку → отправляет сообщение с `canned_response_id` →
`usage_count` шаблона +1. Best-effort: несуществующий `canned_response_id` НЕ валит
отправку (201), без 4xx. Принципалы через `app.dependency_overrides`.
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
    reason="Учёт usage_count требует живой Postgres (CI service container / POSTGRES_AVAILABLE=1).",
)

_SUPPORT = Principal(
    user_id=uuid.uuid4(),
    kind=PrincipalKind.OPERATOR,
    scopes=frozenset({STAFF_SUPPORT_SCOPE}),
    teams=frozenset({TicketTeam.SUPPORT}),
)
_OPERATOR = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)


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


def _create_ticket(client: TestClient) -> str:
    resp = client.post("/api/v1/support/tickets", json={"subject": "s", "type": "OTHER"})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


def test_message_from_template_increments_usage(client: TestClient) -> None:
    _use(_SUPPORT)
    canned = client.post("/api/v1/support/canned-responses", json={"title": "t", "body": "ответ"})
    assert canned.status_code == 201
    cid = canned.json()["data"]["id"]
    assert canned.json()["data"]["usage_count"] == 0

    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    msg = client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        json={"body": "ответ оператора", "is_internal": False, "canned_response_id": cid},
    )
    assert msg.status_code == 201, msg.text

    _use(_SUPPORT)
    got = client.get(f"/api/v1/support/canned-responses/{cid}")
    assert got.json()["data"]["usage_count"] == 1  # инкремент учтён


def test_nonexistent_template_does_not_break_message(client: TestClient) -> None:
    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    msg = client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        json={
            "body": "ответ",
            "is_internal": False,
            "canned_response_id": str(uuid.uuid4()),  # несуществующий шаблон
        },
    )
    # Best-effort: сообщение отправлено несмотря на отсутствие шаблона (не 4xx/5xx).
    assert msg.status_code == 201, msg.text
