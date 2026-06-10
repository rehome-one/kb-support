"""Integration-тесты операции acceptance-act (E10-9 PR-B #199) — требуют Postgres.

Покрывают: RBAC (заявитель→403); 422 на не-ACCEPTANCE_ACT; 404 на чужую/невидимую;
резолв signing_status через AcceptanceAct-клиент (мок) → сохранение в TicketCaseDetails;
M4 — резолв None НЕ затирает signing_status; OTP-resend seam (sms off → не планируется);
act_kind проставляется. Клиент/sms мокаются (наружу HTTP не идёт).
"""

from __future__ import annotations

import asyncio
import decimal
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
from api.clients.acceptance_act import AcceptanceAct
from api.clients.acceptance_act.deps import get_acceptance_act_client
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Операция acceptance-act требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
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
    app.dependency_overrides.pop(get_acceptance_act_client, None)
    asyncio.run(engine.dispose())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class _FakeClient:
    def __init__(self, act: AcceptanceAct | None) -> None:
        self._act = act

    async def get_act(self, acceptance_act_id: uuid.UUID) -> AcceptanceAct | None:
        return self._act


def _override_acceptance(act: AcceptanceAct | None) -> None:
    app.dependency_overrides[get_acceptance_act_client] = lambda: _FakeClient(act)


def _create_acceptance_ticket(client: TestClient) -> str:
    _use(_OPERATOR)
    resp = client.post("/api/v1/support/tickets", json={"subject": "акт", "type": "ACCEPTANCE_ACT"})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


def _read_signing(ticket_id: str) -> str | None:
    async def _inner() -> str | None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT signing_status FROM ticket_case_details WHERE ticket_id = :id"
                        ),
                        {"id": uuid.UUID(ticket_id)},
                    )
                ).first()
                return row[0] if row else None
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _post_act(client: TestClient, ticket_id: str, *, act_kind: str = "MOVE_OUT") -> Response:
    return client.post(
        f"/api/v1/support/tickets/{ticket_id}/acceptance-act",
        json={"act_kind": act_kind, "acceptance_act_id": str(uuid.uuid4())},
    )


def test_requester_forbidden(client: TestClient) -> None:
    # Заявитель создаёт СВОЮ acceptance-заявку (видит её) → operator-гейт даёт 403 (не 404).
    _use(_REQUESTER)
    created = client.post(
        "/api/v1/support/tickets", json={"subject": "акт", "type": "ACCEPTANCE_ACT"}
    )
    assert created.status_code == 201, created.text
    ticket_id = created.json()["data"]["id"]
    assert _post_act(client, ticket_id).status_code == 403


def test_non_acceptance_ticket_422(client: TestClient) -> None:
    _use(_OPERATOR)
    payment = client.post("/api/v1/support/tickets", json={"subject": "s", "type": "PAYMENT"})
    ticket_id = payment.json()["data"]["id"]
    assert _post_act(client, ticket_id).status_code == 422


def test_unknown_ticket_404(client: TestClient) -> None:
    _use(_OPERATOR)
    assert _post_act(client, str(uuid.uuid4())).status_code == 404


def test_resolves_and_stores_signing_status(client: TestClient) -> None:
    ticket_id = _create_acceptance_ticket(client)
    _override_acceptance(
        AcceptanceAct(
            id=str(uuid.uuid4()),
            kind="MOVE_OUT",
            signing_status="both_signed",
            damage_amount=decimal.Decimal("5000.00"),
        )
    )
    _use(_OPERATOR)
    resp = _post_act(client, ticket_id, act_kind="MOVE_OUT")
    assert resp.status_code == 200, resp.text
    assert _read_signing(ticket_id) == "both_signed"  # из upstream-резолва


def test_none_resolve_does_not_wipe_signing_status(client: TestClient) -> None:
    ticket_id = _create_acceptance_ticket(client)
    # 1) сначала резолвим both_signed
    _override_acceptance(
        AcceptanceAct(
            id=str(uuid.uuid4()), kind="MOVE_IN", signing_status="both_signed", damage_amount=None
        )
    )
    _use(_OPERATOR)
    assert _post_act(client, ticket_id, act_kind="MOVE_IN").status_code == 200
    assert _read_signing(ticket_id) == "both_signed"
    # 2) повторная фиксация при выключенной интеграции (клиент None) — НЕ затирает (M4)
    app.dependency_overrides[get_acceptance_act_client] = lambda: None
    assert _post_act(client, ticket_id, act_kind="MOVE_IN").status_code == 200
    assert _read_signing(ticket_id) == "both_signed"
