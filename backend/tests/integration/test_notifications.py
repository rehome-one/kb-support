"""Integration-тесты диспетчера уведомлений (E7-8, #149) — через эндпоинты + БД.

Проверяется врезка: смена статуса оператором → веер запланирован; PATCH без статуса →
нет уведомления; заявитель сам сменил → подавлено; **M1: дедуп-маркер реально персистится**
(перечитка из свежей сессии); ответ оператора → notify_message веер. Требуют Postgres.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketStatus, TicketTeam
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Уведомления требуют живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_OPERATOR = uuid.uuid4()
_REQUESTER = uuid.uuid4()


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


def _operator() -> Principal:
    return Principal(
        user_id=_OPERATOR, kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
    )


def _requester() -> Principal:
    return Principal(user_id=_REQUESTER, kind=PrincipalKind.REQUESTER)


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


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Перехватить все каналы доставки (без сети) и включить config-gates."""
    events: list[str] = []
    monkeypatch.setattr(
        "api.email.outbound.dispatch_email", lambda e, s: events.append("reply_email")
    )
    monkeypatch.setattr(
        "api.notifications.dispatcher.dispatch_email", lambda e, s: events.append("status_email")
    )
    monkeypatch.setattr(
        "api.notifications.dispatcher.dispatch_status_to_chat",
        lambda n, s: events.append("status_chat"),
    )
    monkeypatch.setattr(
        "api.tickets.chat_return.dispatch_operator_reply", lambda r, s: events.append("reply_chat")
    )
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.test")
    monkeypatch.setattr(get_settings(), "smtp_from_address", "support@rehome.one")
    monkeypatch.setattr(get_settings(), "kb_search_api_token", "tok")
    return events


def _email_ticket(
    *, status: str = TicketStatus.OPEN.value, team: str = TicketTeam.SUPPORT.value
) -> str:
    """EMAIL-заявка requester=_REQUESTER, team=SUPPORT (видна оператору), заданный статус."""

    async def _inner() -> str:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                ticket = await TicketRepository(session).create_from_email(
                    subject="Письмо",
                    requester_id=_REQUESTER,
                    custom_fields={"email_from": "r@x.com"},
                )
                await session.execute(
                    text("UPDATE tickets SET status=:s, team=:t WHERE id=:id"),
                    {"s": status, "t": team, "id": ticket.id},
                )
                await session.commit()
                return str(ticket.id)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _ticket_custom_fields(ticket_id: str) -> dict[str, Any]:
    async def _inner() -> dict[str, Any]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                t = await session.get(Ticket, uuid.UUID(ticket_id))
                assert t is not None
                return dict(t.custom_fields or {})
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_resolve_schedules_status_notification_and_persists_marker(
    client: TestClient, captured: list[str]
) -> None:
    _use(_operator())
    ticket_id = _email_ticket(status=TicketStatus.OPEN.value)
    resp = client.post(f"/api/v1/support/tickets/{ticket_id}/resolve", json={})
    assert resp.status_code == 200, resp.text
    assert "status_email" in captured  # EMAIL-заявка → статус-уведомление по email
    # M1: дедуп-маркер реально записан в БД (перечитка из свежей сессии).
    cf = _ticket_custom_fields(ticket_id)
    assert cf["notifications"]["last_status_notified"] == TicketStatus.RESOLVED.value


def test_patch_without_status_no_notification(client: TestClient, captured: list[str]) -> None:
    _use(_operator())
    ticket_id = _email_ticket(status=TicketStatus.OPEN.value)
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"priority": "high"})
    assert resp.status_code == 200, resp.text
    assert captured == []  # статус не менялся → веера нет


def test_requester_self_close_suppressed(client: TestClient, captured: list[str]) -> None:
    # Заявитель сам закрывает свою заявку → не уведомляем его же. RESOLVED→CLOSED
    # разрешён state-machine (OPEN→CLOSED — нет).
    ticket_id = _email_ticket(status=TicketStatus.RESOLVED.value)
    _use(_requester())
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": "CLOSED"})
    assert resp.status_code == 200, resp.text
    assert captured == []


def test_operator_reply_fans_out(client: TestClient, captured: list[str]) -> None:
    _use(_operator())
    ticket_id = _email_ticket(status=TicketStatus.OPEN.value)
    resp = client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        json={"body": "ответ", "is_internal": False},
    )
    assert resp.status_code == 201, resp.text
    assert "reply_email" in captured  # EMAIL-заявка → ответ ушёл письмом через диспетчер
