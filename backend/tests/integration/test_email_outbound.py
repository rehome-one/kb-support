"""Integration-тесты исходящего email-ответа (E7-5, #147) через create_message.

Проверяется врезка `maybe_schedule_email` в эндпоинт: публичный ответ оператора по
EMAIL-заявке → фоновая отправка запланирована (dispatch замокан, без сети); внутренняя
заметка → НЕ запланирована (security NFR-1.3); без smtp_host → выключено. Требуют Postgres.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.email.outbound import OutboundEmail
from api.main import app
from api.tickets.repository import TicketRepository

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="from-email outbound требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_OPERATOR_ID = uuid.uuid4()


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


def _operator() -> Principal:
    return Principal(user_id=_OPERATOR_ID, kind=PrincipalKind.OPERATOR)


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


def _create_email_ticket(email_from: str = "requester@example.com") -> str:
    """Создать EMAIL-заявку с requester_id=оператор (чтобы он её видел) + email_from."""

    async def _inner() -> str:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                ticket = await TicketRepository(session).create_from_email(
                    subject="Письмо заявителя",
                    requester_id=_OPERATOR_ID,
                    custom_fields={"email_from": email_from, "email_message_id": "<orig@mail>"},
                )
                await session.commit()
                return str(ticket.id)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[OutboundEmail]:
    """Перехватить фоновую отправку (без сети): записываем DTO вместо реального SMTP."""
    sent: list[OutboundEmail] = []

    def _record(email: OutboundEmail, settings: Any) -> None:
        sent.append(email)

    monkeypatch.setattr("api.email.outbound.dispatch_email", _record)
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.test")
    monkeypatch.setattr(get_settings(), "smtp_from_address", "support@rehome.one")
    return sent


def _post_message(client: TestClient, ticket_id: str, **body: Any) -> Any:
    return client.post(f"/api/v1/support/tickets/{ticket_id}/messages", json=body)


def test_operator_public_reply_schedules_email(
    client: TestClient, captured: list[OutboundEmail]
) -> None:
    _use(_operator())
    ticket_id = _create_email_ticket()
    resp = _post_message(client, ticket_id, body="Ответ оператора", is_internal=False)
    assert resp.status_code == 201, resp.text
    assert len(captured) == 1
    assert captured[0].to_addr == "requester@example.com"
    assert "[" in captured[0].subject  # номер заявки в Subject


def test_internal_note_does_not_schedule_email(
    client: TestClient, captured: list[OutboundEmail]
) -> None:
    # Security NFR-1.3: внутренняя заметка НЕ уходит письмом заявителю.
    _use(_operator())
    ticket_id = _create_email_ticket()
    resp = _post_message(client, ticket_id, body="Только для операторов", is_internal=True)
    assert resp.status_code == 201, resp.text
    assert captured == []


def test_disabled_without_smtp_host(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[OutboundEmail] = []
    monkeypatch.setattr("api.email.outbound.dispatch_email", lambda e, s: sent.append(e))
    monkeypatch.setattr(get_settings(), "smtp_host", "")  # выключено
    _use(_operator())
    ticket_id = _create_email_ticket()
    resp = _post_message(client, ticket_id, body="Ответ", is_internal=False)
    assert resp.status_code == 201, resp.text
    assert sent == []
