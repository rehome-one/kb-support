"""Integration-тесты каскада ACCEPTANCE_ACT MOVE_OUT+ущерб→COMPENSATION (E10-9 PR-C #199).

Покрывают: MOVE_OUT+damage → один связанный COMPENSATION (claim_amount=damage как ссылка,
channel=SYSTEM, case_state=CLAIM_SUBMITTED) + двусторонний линк в case_details.payload;
идемпотентность (повтор не двоит); MOVE_IN и без-damage → нет каскада. Клиент мокается.
"""

from __future__ import annotations

import asyncio
import decimal
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.clients.acceptance_act import AcceptanceAct
from api.clients.acceptance_act.deps import get_acceptance_act_client
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Каскад acceptance требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
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
    for dep in (get_session, get_current_principal, get_acceptance_act_client):
        app.dependency_overrides.pop(dep, None)
    asyncio.run(engine.dispose())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class _FakeClient:
    def __init__(self, act: AcceptanceAct) -> None:
        self._act = act

    async def get_act(self, acceptance_act_id: uuid.UUID) -> AcceptanceAct:
        return self._act


def _override_act(kind: str, damage: decimal.Decimal | None) -> None:
    act = AcceptanceAct(
        id=str(uuid.uuid4()), kind=kind, signing_status="both_signed", damage_amount=damage
    )
    app.dependency_overrides[get_acceptance_act_client] = lambda: _FakeClient(act)


def _create_acceptance_ticket(client: TestClient) -> str:
    _use(_OPERATOR)
    resp = client.post("/api/v1/support/tickets", json={"subject": "акт", "type": "ACCEPTANCE_ACT"})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


def _post_act(client: TestClient, ticket_id: str, *, act_kind: str = "MOVE_OUT") -> Response:
    return client.post(
        f"/api/v1/support/tickets/{ticket_id}/acceptance-act",
        json={"act_kind": act_kind, "acceptance_act_id": str(uuid.uuid4())},
    )


def _query(sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
    async def _inner() -> list[tuple[Any, ...]]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params)
                return [tuple(row) for row in result.all()]
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _child_ids(parent_id: str) -> list[str]:
    rows = _query(
        "SELECT ticket_id FROM ticket_case_details "
        "WHERE payload->>'source_acceptance_ticket_id' = :pid",
        {"pid": parent_id},
    )
    return [str(r[0]) for r in rows]


def _parent_link(parent_id: str) -> str | None:
    rows = _query(
        "SELECT payload->>'linked_compensation_ticket_id' FROM ticket_case_details "
        "WHERE ticket_id = :pid",
        {"pid": uuid.UUID(parent_id)},
    )
    return rows[0][0] if rows else None


def test_move_out_with_damage_creates_linked_compensation(client: TestClient) -> None:
    parent_id = _create_acceptance_ticket(client)
    _override_act("MOVE_OUT", decimal.Decimal("25000.00"))
    _use(_OPERATOR)
    assert _post_act(client, parent_id, act_kind="MOVE_OUT").status_code == 200

    children = _child_ids(parent_id)
    assert len(children) == 1, "ожидался один связанный COMPENSATION"
    child_id = children[0]
    assert _parent_link(parent_id) == child_id  # двусторонний линк

    rows = _query(
        "SELECT type, channel, claim_amount::text, case_state FROM tickets WHERE id = :cid",
        {"cid": uuid.UUID(child_id)},
    )
    ttype, channel, amount, case_state = rows[0]
    assert ttype == "COMPENSATION"
    assert channel == "SYSTEM"
    assert decimal.Decimal(amount) == decimal.Decimal("25000.00")  # сумма как ссылка
    assert case_state == "CLAIM_SUBMITTED"


def test_cascade_is_idempotent(client: TestClient) -> None:
    parent_id = _create_acceptance_ticket(client)
    _override_act("MOVE_OUT", decimal.Decimal("10000.00"))
    _use(_OPERATOR)
    assert _post_act(client, parent_id, act_kind="MOVE_OUT").status_code == 200
    assert _post_act(client, parent_id, act_kind="MOVE_OUT").status_code == 200
    assert len(_child_ids(parent_id)) == 1, "повторный резолв не должен двоить каскад"


def test_move_in_does_not_cascade(client: TestClient) -> None:
    parent_id = _create_acceptance_ticket(client)
    _override_act("MOVE_IN", decimal.Decimal("9999.00"))
    _use(_OPERATOR)
    assert _post_act(client, parent_id, act_kind="MOVE_IN").status_code == 200
    assert _child_ids(parent_id) == []


def test_no_damage_does_not_cascade(client: TestClient) -> None:
    parent_id = _create_acceptance_ticket(client)
    _override_act("MOVE_OUT", None)
    _use(_OPERATOR)
    assert _post_act(client, parent_id, act_kind="MOVE_OUT").status_code == 200
    assert _child_ids(parent_id) == []
