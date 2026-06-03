"""Integration-тесты учёта пауз SLA (#88) — требуют Postgres.

Через реальные переходы статуса (PATCH и action-эндпоинт) проверяют: вход в
PENDING/WAITING фиксирует паузу, выход сдвигает `resolution_due_at` на её
длительность, `first_response_due_at` не меняется. Длительность паузы задаётся
детерминированно — прямой подстановкой `sla_paused_at` в прошлое.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
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
    reason="Учёт пауз SLA требует живой Postgres (CI service container / POSTGRES_AVAILABLE=1).",
)

_ADMIN = Principal(
    user_id=uuid.uuid4(),
    kind=PrincipalKind.OPERATOR,
    scopes=frozenset({STAFF_ADMIN_SCOPE}),
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


def _backdate_pause(ticket_id: str, seconds: int) -> None:
    """Сдвинуть `sla_paused_at` заявки в прошлое на `seconds` — детерминированная пауза."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE tickets SET sla_paused_at = now() - make_interval(secs => :s)"
                        " WHERE id = :id"
                    ),
                    {"s": seconds, "id": uuid.UUID(ticket_id)},
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def _parse(ts: object) -> datetime.datetime:
    return datetime.datetime.fromisoformat(str(ts))


def _create_ticket_with_sla(client: TestClient, ticket_type: str) -> dict[str, object]:
    # Активная 24/7-политика (priority=100) → дедлайны проставлены на создании.
    _use(_ADMIN)
    created_policy = client.post(
        "/api/v1/support/sla-policies",
        json={
            "name": f"pause-{ticket_type}-#88",
            "applies_to": {"types": [ticket_type]},
            "first_response_minutes": 60,
            "resolution_minutes": 240,
            "priority": 100,
        },
    )
    assert created_policy.status_code == 201, created_policy.text

    _use(_OPERATOR)
    created = client.post("/api/v1/support/tickets", json={"subject": "p", "type": ticket_type})
    assert created.status_code == 201, created.text
    data: dict[str, object] = created.json()["data"]
    assert data["resolution_due_at"] is not None
    assert data["first_response_due_at"] is not None
    return data


def _patch_status(client: TestClient, ticket_id: str, status: str) -> dict[str, object]:
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": status})
    assert resp.status_code == 200, resp.text
    result: dict[str, object] = resp.json()["data"]
    return result


def test_pause_via_patch_shifts_resolution_deadline(client: TestClient) -> None:
    data = _create_ticket_with_sla(client, "ACCOUNT")
    ticket_id = str(data["id"])
    resolution_before = _parse(data["resolution_due_at"])
    first_response_before = data["first_response_due_at"]

    _use(_OPERATOR)
    _patch_status(client, ticket_id, "OPEN")
    _patch_status(client, ticket_id, "PENDING")  # вход в паузу
    _backdate_pause(ticket_id, 3600)  # пауза = 1 час (детерминированно)
    out = _patch_status(client, ticket_id, "OPEN")  # выход из паузы

    resolution_after = _parse(out["resolution_due_at"])
    # Сдвиг ≈ 1 час (точная математика — в unit; здесь допускаем секунды на исполнение).
    shift = (resolution_after - resolution_before).total_seconds()
    assert 3600 <= shift <= 3660, shift
    assert out["first_response_due_at"] == first_response_before  # первый ответ не двигается


def test_pause_via_resolve_action_shifts_resolution_deadline(client: TestClient) -> None:
    data = _create_ticket_with_sla(client, "UTILITIES")
    ticket_id = str(data["id"])
    resolution_before = _parse(data["resolution_due_at"])

    _use(_OPERATOR)
    _patch_status(client, ticket_id, "OPEN")
    _patch_status(client, ticket_id, "WAITING")  # пауза через WAITING
    _backdate_pause(ticket_id, 1800)  # 30 минут

    # Выход из паузы через action-эндпоинт resolve (WAITING→RESOLVED).
    resolved = client.post(f"/api/v1/support/tickets/{ticket_id}/resolve", json={})
    assert resolved.status_code == 200, resolved.text
    resolution_after = _parse(resolved.json()["data"]["resolution_due_at"])
    shift = (resolution_after - resolution_before).total_seconds()
    assert 1800 <= shift <= 1860, shift
