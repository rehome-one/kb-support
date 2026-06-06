"""Integration-тесты веб-формы `POST /tickets/from-web-form` (E7-6, #148).

FR-1.3, ADR-0010 Решение 2: только аутентифицированный заявитель (kind=REQUESTER);
requester_id и channel=WEB_FORM форсятся сервером (anti-spoofing). Вложения →
маркерное начальное сообщение (решение Архитектора #148). Требуют Postgres.
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
    reason="from-web-form требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_PATH = "/api/v1/support/tickets/from-web-form"


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


def _requester() -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER)


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


def _body(**extra: object) -> dict[str, object]:
    return {"subject": "Не работает оплата", "type": "PAYMENT", **extra}


def test_requester_creates_web_form_ticket(client: TestClient) -> None:
    principal = _requester()
    _use(principal)
    resp = client.post(_PATH, json=_body(description="Списали дважды"))
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["channel"] == "WEB_FORM"
    # requester_id — из принципала, не из тела (anti-spoofing).
    assert data["requester_id"] == str(principal.user_id)


def test_channel_and_requester_id_in_body_rejected(client: TestClient) -> None:
    # extra=forbid: попытка подменить канал/заявителя через тело → 422.
    _use(_requester())
    assert client.post(_PATH, json=_body(channel="AI_CHAT")).status_code == 422
    assert client.post(_PATH, json=_body(requester_id=str(uuid.uuid4()))).status_code == 422


@pytest.mark.parametrize("kind", [PrincipalKind.OPERATOR, PrincipalKind.SERVICE])
def test_non_requester_forbidden(client: TestClient, kind: PrincipalKind) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=kind, teams=frozenset({TicketTeam.SUPPORT})))
    assert client.post(_PATH, json=_body()).status_code == 403


def test_unauthenticated_returns_401(client: TestClient) -> None:
    assert client.post(_PATH, json=_body()).status_code == 401


def test_attachments_create_initial_message(client: TestClient) -> None:
    principal = _requester()
    _use(principal)
    file_id = str(uuid.uuid4())
    resp = client.post(_PATH, json=_body(attachments=[file_id]))
    assert resp.status_code == 201, resp.text
    ticket_id = resp.json()["data"]["id"]
    messages = client.get(f"/api/v1/support/tickets/{ticket_id}/messages").json()["data"]
    assert len(messages) == 1
    assert messages[0]["author_type"] == "requester"
    assert messages[0]["attachments"] == [file_id]
    assert messages[0]["is_internal"] is False


def test_no_attachments_creates_no_message(client: TestClient) -> None:
    _use(_requester())
    resp = client.post(_PATH, json=_body(description="Просто вопрос"))
    assert resp.status_code == 201, resp.text
    ticket_id = resp.json()["data"]["id"]
    messages = client.get(f"/api/v1/support/tickets/{ticket_id}/messages").json()["data"]
    assert messages == []
