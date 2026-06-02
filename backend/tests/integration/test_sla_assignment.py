"""Integration-тесты проводки SLA в создание заявки (#87) — требуют Postgres.

Проверяют: матч политики → `sla_policy_id` + дедлайны проставлены; 24/7-политика →
дедлайны = created_at + N (точно); from-chat получает SLA; идемпотентный повтор
from-chat НЕ меняет дедлайны существующей заявки.

Политики создаются с `priority=100` (выше любых из #86-тестов) и узким `applies_to`,
чтобы выбор был детерминирован в общей тест-БД (данные накапливаются между тестами).
"""

from __future__ import annotations

import asyncio
import datetime
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
    reason="Проводка SLA требует живой Postgres (CI service container / POSTGRES_AVAILABLE=1).",
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
_SERVICE = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.SERVICE)


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


def _create_policy(client: TestClient, **body: object) -> str:
    _use(_ADMIN)
    resp = client.post("/api/v1/support/sla-policies", json={"priority": 100, **body})
    assert resp.status_code == 201, resp.text
    policy_id: str = resp.json()["data"]["id"]
    return policy_id


def _parse(ts: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts)


def test_24x7_policy_sets_exact_deadlines(client: TestClient) -> None:
    policy_id = _create_policy(
        client,
        name="24x7 LISTING #87",
        applies_to={"types": ["LISTING"]},
        first_response_minutes=60,
        resolution_minutes=240,
    )  # business_hours_id отсутствует → 24/7

    _use(_OPERATOR)
    created = client.post("/api/v1/support/tickets", json={"subject": "s", "type": "LISTING"})
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["sla_policy_id"] == policy_id

    created_at = _parse(data["created_at"])
    assert _parse(data["first_response_due_at"]) == created_at + datetime.timedelta(minutes=60)
    assert _parse(data["resolution_due_at"]) == created_at + datetime.timedelta(minutes=240)


def test_business_hours_policy_sets_deadlines(client: TestClient) -> None:
    _use(_ADMIN)
    bh = client.post(
        "/api/v1/support/business-hours",
        json={
            "name": "МСК будни #87",
            "timezone": "Europe/Moscow",
            "schedule": {d: [["09:00", "18:00"]] for d in ("mon", "tue", "wed", "thu", "fri")},
        },
    )
    assert bh.status_code == 201, bh.text
    policy_id = _create_policy(
        client,
        name="BH FRAUD #87",
        applies_to={"types": ["FRAUD"], "priorities": ["critical"]},
        first_response_minutes=30,
        resolution_minutes=120,
        business_hours_id=bh.json()["data"]["id"],
    )

    _use(_OPERATOR)
    created = client.post(
        "/api/v1/support/tickets",
        json={"subject": "fraud", "type": "FRAUD", "priority": "critical"},
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["sla_policy_id"] == policy_id
    # Дедлайны проставлены (точные значения зависят от времени прогона; покрыты unit).
    assert data["first_response_due_at"] is not None
    assert data["resolution_due_at"] is not None
    assert _parse(data["resolution_due_at"]) > _parse(data["first_response_due_at"])


def test_from_chat_gets_sla_and_is_idempotent(client: TestClient) -> None:
    policy_id = _create_policy(
        client,
        name="24x7 OTHER #87",
        applies_to={"types": ["OTHER"]},
        first_response_minutes=15,
        resolution_minutes=90,
    )

    _use(_SERVICE)
    session_id = str(uuid.uuid4())
    payload = {
        "chat_session_id": session_id,
        "requester_id": str(uuid.uuid4()),
        "transcript": [{"role": "user", "content": "помогите"}],
    }
    first = client.post("/api/v1/support/tickets/from-chat", json=payload)
    assert first.status_code == 201, first.text
    fdata = first.json()["data"]
    assert fdata["sla_policy_id"] == policy_id
    assert fdata["first_response_due_at"] is not None

    # Повтор той же сессии — идемпотентно: та же заявка, дедлайны НЕ изменились.
    second = client.post("/api/v1/support/tickets/from-chat", json=payload)
    assert second.status_code == 201
    sdata = second.json()["data"]
    assert sdata["id"] == fdata["id"]
    assert sdata["first_response_due_at"] == fdata["first_response_due_at"]
    assert sdata["resolution_due_at"] == fdata["resolution_due_at"]
