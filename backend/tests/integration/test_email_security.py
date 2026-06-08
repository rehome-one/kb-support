"""Security/edge-приёмка входящего email на ГРАНИЦЕ канала (E7-10, #151).

Закрывает genuine gap: spoofed sender НА HTTP-эндпоинте `/from-email` (на уровне
ingestion-функции это есть в test_email_ingestion; здесь — через публичный контур) +
HTTP-пин «письмо без номера → новая заявка». malformed/oversized уже покрыты на эндпоинте
(test_email_endpoint), CLOSED→new — на уровне ingestion — не дублируем. Требуют Postgres.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import EMAIL_SENDER_ACTOR_ID
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.messages import TicketMessage

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="from-email security требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_PATH = "/api/v1/support/tickets/from-email"


def _use_service() -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=uuid.uuid4(), kind=PrincipalKind.SERVICE
    )


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
    _use_service()
    with TestClient(app) as test_client:
        yield test_client


def _raw(*, from_addr: str, subject: str, body: str = "тело") -> str:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{uuid.uuid4()}@mail>"
    msg.set_content(body)
    return base64.b64encode(msg.as_bytes()).decode("ascii")


def _db_messages(ticket_id: str) -> list[TicketMessage]:
    async def _inner() -> list[TicketMessage]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                rows = await session.execute(
                    select(TicketMessage).where(TicketMessage.ticket_id == uuid.UUID(ticket_id))
                )
                return list(rows.scalars().all())
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_endpoint_spoofed_reply_does_not_change_requester(client: TestClient) -> None:
    """Security NFR-1.3/ADR-0010 Реш.3: ответ с ЧУЖИМ From на активную заявку через
    HTTP-эндпоинт НЕ меняет requester заявки; автор инъекции = sentinel (platform off)."""
    first = client.post(
        _PATH, json={"raw_message": _raw(from_addr="real@x.com", subject="Проблема")}
    )
    assert first.status_code == 201, first.text
    data = first.json()["data"]
    ticket_id, number = data["id"], data["number"]
    original_requester = data["requester_id"]

    spoof = client.post(
        _PATH,
        json={
            "raw_message": _raw(
                from_addr="attacker@evil.com", subject=f"Re: {number}", body="инъекция"
            )
        },
    )
    assert spoof.status_code == 201, spoof.text
    assert spoof.json()["data"]["id"] == ticket_id  # привязалось к той же заявке
    assert spoof.json()["data"]["requester_id"] == original_requester  # requester НЕ изменён

    injected = next(m for m in _db_messages(ticket_id) if m.body == "инъекция")
    assert injected.author_id == EMAIL_SENDER_ACTOR_ID  # спуфер не выдаёт себя за заявителя
    assert injected.is_internal is False  # входящее письмо не становится внутренней заметкой


def test_endpoint_no_number_creates_new_ticket(client: TestClient) -> None:
    """Письмо без номера в теме → новая заявка (HTTP-пин)."""
    resp = client.post(_PATH, json={"raw_message": _raw(from_addr="a@b.com", subject="Без номера")})
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["channel"] == "EMAIL"
