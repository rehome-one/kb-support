"""Integration-тесты эндпоинта `POST /tickets/from-email` (E7-3 PR-B, #145).

Контур m2m над ядром PR-A: kind=SERVICE-only (anti-spoofing, ADR-0010 Реш.3);
тело — base64 RFC822; битый base64 → 400; превышение размера → 422; malformed
письмо принимается (не 4xx). Требуют Postgres.
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
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam
from api.tickets.messages import TicketMessage

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="from-email требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_PATH = "/api/v1/support/tickets/from-email"


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


def _service() -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=PrincipalKind.SERVICE)


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


def _db_messages(ticket_id: str) -> list[TicketMessage]:
    """Прочитать сообщения заявки напрямую из БД: EMAIL-заявка не видна ни SERVICE,
    ни оператору без команды (team=None, requester=sentinel) — HTTP GET тут не годится."""

    async def _inner() -> list[TicketMessage]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                rows = await session.execute(
                    select(TicketMessage)
                    .where(TicketMessage.ticket_id == uuid.UUID(ticket_id))
                    .order_by(TicketMessage.created_at)
                )
                return list(rows.scalars().all())
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _raw_email(
    *,
    subject: str = "Нужна помощь",
    from_addr: str = "ivan@example.com",
    message_id: str | None = None,
    body: str = "Текст письма",
    attachment: tuple[str, bytes] | None = None,
) -> str:
    """Собрать base64 RFC822-письмо для тела запроса."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id or f"<{uuid.uuid4()}@mail>"
    msg.set_content(body)
    if attachment is not None:
        name, data = attachment
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return base64.b64encode(msg.as_bytes()).decode("ascii")


def test_service_creates_email_ticket(client: TestClient) -> None:
    _use(_service())
    resp = client.post(_PATH, json={"raw_message": _raw_email(body="проблема с оплатой")})
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["channel"] == "EMAIL"
    # Тело письма живёт в первом сообщении (вариант A), description пуст.
    assert data["description"] == ""
    ticket_id = data["id"]
    messages = _db_messages(ticket_id)
    assert len(messages) == 1
    assert messages[0].body == "проблема с оплатой"
    # NFR-1.3: входящее письмо НЕ может стать внутренней заметкой (сквозь контур).
    assert messages[0].is_internal is False


@pytest.mark.parametrize("kind", [PrincipalKind.OPERATOR, PrincipalKind.REQUESTER])
def test_non_service_forbidden(client: TestClient, kind: PrincipalKind) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=kind, teams=frozenset({TicketTeam.SUPPORT})))
    assert client.post(_PATH, json={"raw_message": _raw_email()}).status_code == 403


def test_unauthenticated_returns_401(client: TestClient) -> None:
    assert client.post(_PATH, json={"raw_message": _raw_email()}).status_code == 401


def test_reply_by_number_attaches_to_same_ticket(client: TestClient) -> None:
    _use(_service())
    first = client.post(_PATH, json={"raw_message": _raw_email(body="первое")})
    assert first.status_code == 201, first.text
    number = first.json()["data"]["number"]
    ticket_id = first.json()["data"]["id"]

    reply = client.post(
        _PATH,
        json={"raw_message": _raw_email(subject=f"Re: {number}", body="дополнение")},
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["data"]["id"] == ticket_id  # та же заявка, не новая
    messages = _db_messages(ticket_id)
    assert {m.body for m in messages} == {"первое", "дополнение"}


def test_duplicate_message_id_is_idempotent(client: TestClient) -> None:
    _use(_service())
    mid = f"<{uuid.uuid4()}@mail>"
    first = client.post(_PATH, json={"raw_message": _raw_email(message_id=mid, body="один")})
    assert first.status_code == 201, first.text
    ticket_id = first.json()["data"]["id"]

    again = client.post(_PATH, json={"raw_message": _raw_email(message_id=mid, body="дубль")})
    assert again.status_code == 201, again.text
    assert again.json()["data"]["id"] == ticket_id  # дедуп → та же заявка
    assert len(_db_messages(ticket_id)) == 1  # дубль не добавил сообщение


def test_invalid_base64_returns_400(client: TestClient) -> None:
    _use(_service())
    resp = client.post(_PATH, json={"raw_message": "не-base64-!!!"})
    assert resp.status_code == 400, resp.text


def test_oversized_message_returns_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(_service())
    monkeypatch.setattr(get_settings(), "email_raw_max_bytes", 10)
    resp = client.post(_PATH, json={"raw_message": _raw_email(body="это письмо длиннее лимита")})
    assert resp.status_code == 422, resp.text


def test_malformed_email_is_accepted_not_4xx(client: TestClient) -> None:
    _use(_service())
    # Не-RFC822 мусор: парсер #144 malformed-safe → контур НЕ отдаёт 4xx, письмо
    # принимается как заявка (корреспонденцию не теряем). Само содержимое разбора —
    # ответственность парсера (#144), здесь проверяем поведение контура.
    raw = base64.b64encode(b"\xff\xfe not a real email at all").decode("ascii")
    resp = client.post(_PATH, json={"raw_message": raw})
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["channel"] == "EMAIL"


def test_oversized_attachment_filtered(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(_service())
    monkeypatch.setattr(get_settings(), "email_attachment_max_bytes", 4)
    raw = _raw_email(body="с вложением", attachment=("big.bin", b"0123456789"))
    resp = client.post(_PATH, json={"raw_message": raw})
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert "big.bin" in data["custom_fields"]["email_oversized_attachments"]
