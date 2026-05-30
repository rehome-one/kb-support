"""Integration-тесты POST/GET тикетов + security NFR-1.2 (требуют Postgres).

Запускается в CI (service container) и локально при `POSTGRES_AVAILABLE=1`.
Принципал инжектится через `app.dependency_overrides` (seam #6 — реальная
JWT/сессионная валидация в #29). Заявки коммитятся в эфемерную тестовую БД;
изоляция между тестами не требуется (данные не конфликтуют, number уникален).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam, TicketType
from api.tickets.history import TicketHistoryRepository, record_changes
from api.tickets.repository import TicketRepository
from api.tickets.schemas import TicketCreate

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason=(
        "POST/GET тикетов требуют живой Postgres. Запускается в CI (service"
        " container) и локально при POSTGRES_AVAILABLE=1."
    ),
)


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture(autouse=True)
def _override_db_session() -> Iterator[None]:
    """Переопределить get_session на NullPool-движок.

    Глобальный QueuePool-движок кеширует asyncpg-соединения, привязанные к
    event loop первого TestClient; последующие тесты создают новый loop →
    cross-loop ошибки. NullPool открывает свежее соединение на текущем loop.
    """
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


def _create(client: TestClient, **extra: object) -> Response:
    payload = {"subject": "Нужна помощь", "type": "PAYMENT", **extra}
    return client.post("/api/v1/support/tickets", json=payload)


def _set_team(ticket_id: str, team_value: str) -> None:
    """Назначить команду заявке напрямую в БД (assign endpoint — #12)."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE tickets SET team = :t WHERE id = :id"),
                    {"t": team_value, "id": uuid.UUID(ticket_id)},
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def test_create_returns_201_with_defaults(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    resp = _create(client)
    assert resp.status_code == 201
    payload = resp.json()
    data = payload["data"]
    assert payload["request_id"]
    assert data["requester_id"] == str(user)
    assert data["status"] == "NEW"
    assert data["access_level"] == "LOGGED"
    assert data["priority"] == "normal"
    assert data["channel"] == "WEB_FORM"
    assert data["number"].startswith("RH-")
    assert data["case_state"] is None


def test_owner_can_get_own_ticket(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == ticket_id


def test_requester_cannot_see_others_ticket(client: TestClient) -> None:
    """NFR-1.2: заявитель B не видит заявку A, даже зная её id → 404."""
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    _use(Principal(user_id=user_a, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]

    _use(Principal(user_id=user_b, kind=PrincipalKind.REQUESTER))
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_requester_id_from_body_ignored_for_requester(client: TestClient) -> None:
    """Заявитель не может подменить requester_id через payload (anti-spoofing)."""
    user_a, victim = uuid.uuid4(), uuid.uuid4()
    _use(Principal(user_id=user_a, kind=PrincipalKind.REQUESTER))
    resp = _create(client, requester_id=str(victim))
    assert resp.status_code == 201
    assert resp.json()["data"]["requester_id"] == str(user_a)


def test_operator_creates_on_behalf_of_requester(client: TestClient) -> None:
    operator, requester = uuid.uuid4(), uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    resp = _create(client, requester_id=str(requester))
    assert resp.status_code == 201
    assert resp.json()["data"]["requester_id"] == str(requester)


def test_request_id_echoed_from_header(client: TestClient) -> None:
    request_id = uuid.uuid4()
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    resp = client.post(
        "/api/v1/support/tickets",
        json={"subject": "x", "type": "PAYMENT"},
        headers={"X-Request-Id": str(request_id)},
    )
    assert resp.status_code == 201
    assert resp.json()["request_id"] == str(request_id)


def test_invalid_request_id_header_falls_back_to_generated(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    resp = client.post(
        "/api/v1/support/tickets",
        json={"subject": "x", "type": "PAYMENT"},
        headers={"X-Request-Id": "not-a-uuid"},
    )
    assert resp.status_code == 201
    # Невалидный заголовок → сгенерированный валидный uuid (парсится без ошибки).
    uuid.UUID(resp.json()["request_id"])


def test_create_writes_created_history_visible_to_operator(client: TestClient) -> None:
    """DoD #9: создание пишет первую строку journal (action=created)."""
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]  # requester_id == operator (owner)
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/history")
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert any(r["action"] == "created" for r in rows)
    assert rows[0]["actor_id"] == str(operator)


def test_history_forbidden_for_requester(client: TestClient) -> None:
    """Журнал — внутренние данные (§3.7): заявителю-владельцу → 403."""
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/history")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_history_not_found_for_non_owner(client: TestClient) -> None:
    """Чужая заявка → 404 (anti-enumeration) до проверки оператор/нет."""
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/history")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_record_changes_persists_status_and_reassign() -> None:
    """DoD #9: механизм auto-record пишет status_changed/reassigned (persist)."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            actor = uuid.uuid4()
            ticket = await TicketRepository(session).create(
                TicketCreate(subject="x", type=TicketType.PAYMENT),
                Principal(
                    user_id=actor,
                    kind=PrincipalKind.OPERATOR,
                    teams=frozenset({TicketTeam.SUPPORT}),
                ),
            )
            await session.commit()
            history = TicketHistoryRepository(session)
            await record_changes(
                history,
                ticket.id,
                actor,
                {"status": "NEW", "assignee_id": None},
                {"status": "OPEN", "assignee_id": str(uuid.uuid4())},
            )
            await session.commit()
            rows = await history.list_for_ticket(ticket.id)
            actions = [r.action for r in rows]
            assert "created" in actions
            assert "status_changed" in actions
            assert "reassigned" in actions
            # Порядок DESC по created_at (новые сверху).
            assert rows[0].created_at >= rows[-1].created_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_get_session_dependency_yields_session() -> None:
    """Прямой прогон production-зависимости get_session (в API-тестах переопределена)."""
    async for session in get_session():
        assert isinstance(session, AsyncSession)
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        break


def test_operator_sees_ticket_of_own_team_only(client: TestClient) -> None:
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, TicketTeam.SUPPORT.value)

    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    assert client.get(f"/api/v1/support/tickets/{ticket_id}").status_code == 200

    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.LEGAL}),
        )
    )
    assert client.get(f"/api/v1/support/tickets/{ticket_id}").status_code == 404
