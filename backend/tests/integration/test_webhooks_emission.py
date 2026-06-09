"""Integration-тесты эмиссии webhook-событий (E10-8 PR-B #198) — требуют Postgres.

Покрывают: `ticket.case_decided` (после /decision) и `ticket.payout_released` (на переходе
в PAID, «4 глаза»); **NFR-1.3/ФЗ-152** — payload без ПДн (`decision_reason` не утекает);
единичность по триггеру (первый аппрув «4 глаза» НЕ эмитит — заявка ещё PAYOUT_PENDING).
Доставка замокана (`deliver_webhook`) — реальный HTTP наружу не идёт.
"""

from __future__ import annotations

import asyncio
import json
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
from api.auth.scopes import STAFF_ADMIN_SCOPE
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam
from api.webhooks.events import WebhookDelivery

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Эмиссия webhook требует живой Postgres (CI service container / POSTGRES_AVAILABLE=1).",
)

_ADMIN = Principal(
    user_id=uuid.uuid4(),
    kind=PrincipalKind.OPERATOR,
    scopes=frozenset({STAFF_ADMIN_SCOPE}),
    teams=frozenset({TicketTeam.SUPPORT}),
)
_CLAIMS_OP = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.LEGAL})
)


def _support_op() -> Principal:
    return Principal(
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


def _set_field(ticket_id: str, column: str, value: str) -> None:
    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(f"UPDATE tickets SET {column} = :v WHERE id = :id"),  # noqa: S608
                    {"v": value, "id": uuid.UUID(ticket_id)},
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def _create(client: TestClient) -> Response:
    return client.post("/api/v1/support/tickets", json={"subject": "тема", "type": "PAYMENT"})


def _subscribe(client: TestClient, *events: str) -> None:
    _use(_ADMIN)
    resp = client.post(
        "/api/v1/support/webhooks",
        json={"url": f"https://sub-{uuid.uuid4().hex}.example.com/h", "events": list(events)},
    )
    assert resp.status_code == 201, resp.text


def test_case_decided_emits_whitelist_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[WebhookDelivery] = []

    async def _fake(url: str, secret: str, delivery: WebhookDelivery, settings: object) -> None:
        captured.append(delivery)

    monkeypatch.setattr("api.webhooks.dispatcher.deliver_webhook", _fake)

    _subscribe(client, "ticket.case_decided")
    _use(_CLAIMS_OP)
    ticket_id = _create(client).json()["data"]["id"]
    _set_field(ticket_id, "case_state", "UNDER_REVIEW")

    resp = client.post(
        f"/api/v1/support/tickets/{ticket_id}/decision",
        json={"decision": "PARTIAL", "approved_amount": 1000.00, "reason": "ПДн-причина-XYZ"},
    )
    assert resp.status_code == 200, resp.text

    assert captured, "ожидалась доставка ticket.case_decided"
    delivery = captured[0]
    assert delivery.event == "ticket.case_decided"
    body = json.loads(delivery.payload)
    assert body["data"]["decision"] == "PARTIAL"
    assert body["data"]["approved_amount"] == "1000.00"  # строка (FR-9.8)
    # ФЗ-152/NFR-1.3: свободный текст причины НЕ утекает подписчику.
    for d in captured:
        assert "ПДн-причина-XYZ" not in d.payload.decode()


def test_payout_released_emits_only_on_paid_transition(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[WebhookDelivery] = []

    async def _fake(url: str, secret: str, delivery: WebhookDelivery, settings: object) -> None:
        captured.append(delivery)

    monkeypatch.setattr("api.webhooks.dispatcher.deliver_webhook", _fake)

    _subscribe(client, "ticket.payout_released")
    op_a, op_b = _support_op(), _support_op()
    _use(op_a)
    ticket_id = _create(client).json()["data"]["id"]
    _set_field(ticket_id, "team", "support")  # оба оператора видят заявку
    _set_field(ticket_id, "case_state", "PAYOUT_PENDING")

    # Первый аппрув «4 глаза»: остаётся PAYOUT_PENDING → НЕ newly-paid → НЕТ эмиссии.
    r1 = client.post(f"/api/v1/support/tickets/{ticket_id}/case-state", json={"case_state": "PAID"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["case_state"] == "PAYOUT_PENDING"
    assert captured == [], "первый аппрув не должен эмитить payout_released"

    # Второй, ДРУГОЙ оператор → переход в PAID → эмиссия.
    _use(op_b)
    r2 = client.post(f"/api/v1/support/tickets/{ticket_id}/case-state", json={"case_state": "PAID"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["case_state"] == "PAID"
    assert captured, "переход в PAID должен эмитить payout_released"
    assert all(d.event == "ticket.payout_released" for d in captured)
