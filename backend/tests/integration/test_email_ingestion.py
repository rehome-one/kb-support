"""Integration-тесты ingestion входящего email (E7-3, #145) — требуют Postgres.

Своя NullPool-сессия в откатываемой транзакции (как test_sla_repository) — изоляция
и один event loop. Фейковые platform/kb_files-клиенты (config-gated инъекция). Проверка:
привязка/создание, дедуп Message-ID, резолв/sentinel (anti-spoofing), вложения,
security (is_internal=False; spoofed From на чужую заявку не меняет requester).
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.system_actors import EMAIL_SENDER_ACTOR_ID
from api.clients.errors import ExternalServiceError
from api.clients.kb_files.models import StoredFile
from api.clients.platform.models import Booking, Collaborator, Premises, UserProfile
from api.config import get_settings
from api.email.ingestion import ingest_email
from api.email.parser import ParsedAttachment, ParsedEmail
from api.tickets.enums import TicketChannel, TicketStatus
from api.tickets.messages import TicketMessage

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Требует живой Postgres (CI service container или POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")


def _in_rolled_back_session(body: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def _inner() -> T:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                trans = await conn.begin()
                factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
                async with factory() as session:
                    result = await body(session)
                await trans.rollback()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


class _FakePlatform:
    """platform-клиент для ingestion: get_user_by_email значим, прочее — заглушки None
    (удовлетворяют PlatformClient Protocol, ingestion их не зовёт)."""

    def __init__(self, user: UserProfile | None) -> None:
        self._user = user

    async def get_user_by_email(self, email: str) -> UserProfile | None:
        return self._user

    async def get_user(self, user_id: uuid.UUID) -> UserProfile | None:
        return None

    async def get_premises(self, premises_id: uuid.UUID) -> Premises | None:
        return None

    async def get_booking(self, booking_id: uuid.UUID) -> Booking | None:
        return None

    async def get_collaborator(self, collaborator_id: uuid.UUID) -> Collaborator | None:
        return None


class _FakeKbFiles:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.uploaded: list[str] = []

    async def upload(self, *, filename: str, content_type: str, content: bytes) -> StoredFile:
        if self.fail:
            raise ExternalServiceError("kb_files", "upload", "boom")
        self.uploaded.append(filename)
        return StoredFile(
            id=str(uuid.uuid4()), filename=filename, content_type=content_type, size=len(content)
        )


def _email(
    *,
    subject: str = "Нужна помощь",
    from_addr: str = "ivan@example.com",
    message_id: str | None = None,
    ticket_number: str | None = None,
    body: str = "Текст письма",
    attachments: tuple[ParsedAttachment, ...] = (),
    oversized: tuple[str, ...] = (),
) -> ParsedEmail:
    return ParsedEmail(
        from_addr=from_addr,
        message_id=message_id or f"<{uuid.uuid4()}@mail>",
        subject=subject,
        text_body=body,
        ticket_number=ticket_number,
        attachments=attachments,
        oversized_filenames=oversized,
        date=None,
        in_reply_to=None,
        references=(),
        parse_error=None,
    )


async def _messages(session: AsyncSession, ticket_id: uuid.UUID) -> list[TicketMessage]:
    rows = await session.execute(select(TicketMessage).where(TicketMessage.ticket_id == ticket_id))
    return list(rows.scalars().all())


def test_new_email_creates_email_ticket_with_sentinel_requester() -> None:
    async def body(session: AsyncSession) -> None:
        parsed = _email(body="Здравствуйте, проблема с оплатой")
        result = await ingest_email(session, parsed, platform_client=None, kb_files_client=None)
        assert result.created is True
        assert result.deduped is False
        t = result.ticket
        assert t.channel == TicketChannel.EMAIL.value
        assert t.description == ""  # тело — в сообщении (email-native)
        assert t.requester_id == EMAIL_SENDER_ACTOR_ID  # platform off → sentinel
        assert t.custom_fields["email_from"] == "ivan@example.com"
        msgs = await _messages(session, t.id)
        assert len(msgs) == 1
        assert msgs[0].body == "Здравствуйте, проблема с оплатой"
        assert msgs[0].is_internal is False
        assert msgs[0].author_id == EMAIL_SENDER_ACTOR_ID

    _in_rolled_back_session(body)


def test_reply_attaches_to_active_ticket_by_number() -> None:
    async def body(session: AsyncSession) -> None:
        first = await ingest_email(
            session, _email(body="первое"), platform_client=None, kb_files_client=None
        )
        number = first.ticket.number
        reply = _email(subject=f"Re: {number} ответ", ticket_number=number, body="дополнение")
        result = await ingest_email(session, reply, platform_client=None, kb_files_client=None)
        assert result.created is False
        assert result.ticket.id == first.ticket.id
        msgs = await _messages(session, first.ticket.id)
        assert len(msgs) == 2
        assert {m.body for m in msgs} == {"первое", "дополнение"}

    _in_rolled_back_session(body)


def test_reply_to_closed_number_creates_new_ticket() -> None:
    async def body(session: AsyncSession) -> None:
        first = await ingest_email(session, _email(), platform_client=None, kb_files_client=None)
        number = first.ticket.number
        first.ticket.status = TicketStatus.CLOSED.value
        await session.flush()
        reply = _email(subject=f"Re: {number}", ticket_number=number, body="после закрытия")
        result = await ingest_email(session, reply, platform_client=None, kb_files_client=None)
        assert result.created is True  # CLOSED не реанимируется
        assert result.ticket.id != first.ticket.id

    _in_rolled_back_session(body)


def test_duplicate_message_id_is_idempotent() -> None:
    async def body(session: AsyncSession) -> None:
        mid = "<dup-123@mail>"
        first = await ingest_email(
            session, _email(message_id=mid), platform_client=None, kb_files_client=None
        )
        again = await ingest_email(
            session,
            _email(message_id=mid, body="другой текст"),
            platform_client=None,
            kb_files_client=None,
        )
        assert again.deduped is True
        assert again.ticket.id == first.ticket.id
        # Дубль не создал нового сообщения.
        assert len(await _messages(session, first.ticket.id)) == 1

    _in_rolled_back_session(body)


def test_platform_resolve_sets_requester_from_user() -> None:
    async def body(session: AsyncSession) -> None:
        user_id = uuid.uuid4()
        profile = UserProfile(
            id=user_id,
            display_name="Иван",
            email="ivan@example.com",
            phone=None,
            role="tenant",
            is_active=True,
            created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )
        result = await ingest_email(
            session, _email(), platform_client=_FakePlatform(profile), kb_files_client=None
        )
        assert result.ticket.requester_id == user_id

    _in_rolled_back_session(body)


def test_attachments_uploaded_to_kb_files() -> None:
    async def body(session: AsyncSession) -> None:
        att = ParsedAttachment(
            filename="doc.pdf", content_type="application/pdf", content=b"PDF", size=3
        )
        kb = _FakeKbFiles()
        result = await ingest_email(
            session, _email(attachments=(att,)), platform_client=None, kb_files_client=kb
        )
        msgs = await _messages(session, result.ticket.id)
        assert len(msgs[0].attachments) == 1  # file_id сохранён
        assert kb.uploaded == ["doc.pdf"]

    _in_rolled_back_session(body)


def test_kb_files_off_defers_attachments() -> None:
    async def body(session: AsyncSession) -> None:
        att = ParsedAttachment(
            filename="big.bin", content_type="application/octet-stream", content=b"x", size=1
        )
        result = await ingest_email(
            session, _email(attachments=(att,)), platform_client=None, kb_files_client=None
        )
        msgs = await _messages(session, result.ticket.id)
        assert msgs[0].attachments == []
        assert result.ticket.custom_fields["email_attachments_deferred"]["deferred_count"] == 1

    _in_rolled_back_session(body)


def test_spoofed_from_reply_does_not_change_ticket_requester() -> None:
    """Security (NFR-1.3/anti-spoofing): ответ с ЧУЖИМ From на активную заявку НЕ меняет
    requester заявки; автор сообщения — sentinel (platform off), не исходный заявитель."""

    async def body(session: AsyncSession) -> None:
        real_user = uuid.uuid4()
        profile = UserProfile(
            id=real_user,
            display_name="Реальный",
            email="real@example.com",
            phone=None,
            role="tenant",
            is_active=True,
            created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )
        # Заявка создана с резолвом реального заявителя.
        first = await ingest_email(
            session,
            _email(from_addr="real@example.com"),
            platform_client=_FakePlatform(profile),
            kb_files_client=None,
        )
        assert first.ticket.requester_id == real_user
        number = first.ticket.number
        # Спуфер отвечает на ту же заявку, platform off → автор = sentinel.
        spoof = _email(
            subject=f"Re: {number}",
            ticket_number=number,
            from_addr="attacker@evil.com",
            body="инъекция",
        )
        result = await ingest_email(session, spoof, platform_client=None, kb_files_client=None)
        assert result.ticket.id == first.ticket.id
        assert result.ticket.requester_id == real_user  # НЕ изменён
        msgs = await _messages(session, first.ticket.id)
        injected = next(m for m in msgs if m.body == "инъекция")
        assert injected.author_id == EMAIL_SENDER_ACTOR_ID  # не выдаёт себя за заявителя
        assert injected.is_internal is False

    _in_rolled_back_session(body)


def test_message_count_helper_consistent() -> None:
    async def body(session: AsyncSession) -> None:
        result = await ingest_email(session, _email(), platform_client=None, kb_files_client=None)
        count = await session.scalar(
            select(func.count())
            .select_from(TicketMessage)
            .where(TicketMessage.ticket_id == result.ticket.id)
        )
        assert count == 1

    _in_rolled_back_session(body)
