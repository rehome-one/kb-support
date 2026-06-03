"""Integration-тесты first_responded_at (#89) — требуют Postgres.

FR-4.3: `first_responded_at` фиксируется на ПЕРВОМ публичном ответе оператора.
NFR-1.3 (security): внутренняя заметка оператора ответом НЕ считается; ответ
заявителя — тоже. Идемпотентно: повторный ответ не перезаписывает.
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
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="first_responded_at требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_REQUESTER_ID = uuid.uuid4()
_OPERATOR = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)
_REQUESTER = Principal(user_id=_REQUESTER_ID, kind=PrincipalKind.REQUESTER)


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


def _create_ticket(client: TestClient, *, requester_id: str | None = None) -> str:
    body: dict[str, object] = {"subject": "fr", "type": "ACCOUNT"}
    if requester_id is not None:
        body["requester_id"] = requester_id
    resp = client.post("/api/v1/support/tickets", json=body)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


def _first_responded_at(client: TestClient, ticket_id: str) -> object:
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["first_responded_at"]


def _post_message(client: TestClient, ticket_id: str, *, is_internal: bool) -> None:
    resp = client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        json={"body": "ответ", "is_internal": is_internal},
    )
    assert resp.status_code == 201, resp.text


def test_operator_public_reply_sets_first_responded_at(client: TestClient) -> None:
    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    assert _first_responded_at(client, ticket_id) is None

    _post_message(client, ticket_id, is_internal=False)
    first = _first_responded_at(client, ticket_id)
    assert first is not None

    # Идемпотентность: повторный публичный ответ не перезаписывает метку.
    _post_message(client, ticket_id, is_internal=False)
    assert _first_responded_at(client, ticket_id) == first


def test_operator_internal_note_does_not_set(client: TestClient) -> None:
    # NFR-1.3: внутренняя заметка ответом заявителю не является.
    _use(_OPERATOR)
    ticket_id = _create_ticket(client)
    _post_message(client, ticket_id, is_internal=True)
    assert _first_responded_at(client, ticket_id) is None


def test_requester_reply_does_not_set(client: TestClient) -> None:
    # Заявка создаётся оператором от имени заявителя; отвечает заявитель — не считается.
    _use(_OPERATOR)
    ticket_id = _create_ticket(client, requester_id=str(_REQUESTER_ID))

    _use(_REQUESTER)
    _post_message(client, ticket_id, is_internal=False)
    # Читаем как заявитель (владелец); оператор без команды эту заявку не видит (NFR-1.2).
    assert _first_responded_at(client, ticket_id) is None
