"""Integration-тесты IMAP-приёма (E7-4, #146) — фейковый ящик + реальная БД.

Сеть изолирована `ImapMailbox`-фейком (без IMAP-сервера). Проверяется оркестрация
`poll_and_ingest`: per-message commit (Д4), пометка обработанного, дедуп по Message-ID,
пропуск oversized, изоляция сбоя ingest (best-effort), перенос в папку. Требуют Postgres.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import Awaitable, Callable
from email.message import EmailMessage
from typing import TypeVar

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.config import get_settings
from api.email.ingestion import ingest_email as _real_ingest
from api.email.worker.poll import FetchedMessage, poll_and_ingest
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="IMAP-приём требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")

_BIG = 26 * 1024 * 1024


def _with_session(body: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Реальная NullPool-сессия (poll коммитит per-message — откатываемый tx не годится)."""

    async def _inner() -> T:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                return await body(session)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


class _FakeMailbox:
    """Фейковый ящик: отдаёт заранее заданные письма, пишет лог обработки."""

    def __init__(self, messages: list[FetchedMessage]) -> None:
        self._messages = messages
        self.processed: list[tuple[bytes, str | None]] = []
        self.closed = False

    def fetch_unseen(self, limit: int) -> list[FetchedMessage]:
        return self._messages[:limit]

    def mark_processed(self, uid: bytes, *, move_to: str | None) -> None:
        self.processed.append((uid, move_to))

    def close(self) -> None:
        self.closed = True


def _msg(
    *, subject: str = "Тема", message_id: str | None = None, body: str = "тело"
) -> FetchedMessage:
    mail = EmailMessage()
    mail["From"] = "sender@example.com"
    mail["Subject"] = subject
    mail["Message-ID"] = message_id or f"<{uuid.uuid4()}@mail>"
    mail.set_content(body)
    return FetchedMessage(uid=uuid.uuid4().hex.encode(), raw=mail.as_bytes())


async def _count_by_mid(session: AsyncSession, mid: str) -> int:
    stmt = (
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.custom_fields["email_message_id"].astext == mid)
    )
    return (await session.execute(stmt)).scalar_one()


def test_poll_creates_tickets_and_marks_processed() -> None:
    mid_a = f"<{uuid.uuid4()}@mail>"
    mailbox = _FakeMailbox([_msg(message_id=mid_a, body="первое"), _msg(body="второе")])

    async def body(session: AsyncSession) -> None:
        result = await poll_and_ingest(
            session,
            mailbox,
            batch_limit=50,
            raw_max_bytes=_BIG,
            attachment_max_bytes=_BIG,
            processed_mailbox=None,
        )
        assert result.fetched == 2
        assert result.ingested == 2
        assert result.failed == 0
        assert len(mailbox.processed) == 2  # оба помечены обработанными
        assert await _count_by_mid(session, mid_a) == 1

    _with_session(body)


def test_duplicate_message_id_deduped() -> None:
    mid = f"<{uuid.uuid4()}@mail>"
    mailbox = _FakeMailbox([_msg(message_id=mid, body="один"), _msg(message_id=mid, body="дубль")])

    async def body(session: AsyncSession) -> None:
        result = await poll_and_ingest(
            session,
            mailbox,
            batch_limit=50,
            raw_max_bytes=_BIG,
            attachment_max_bytes=_BIG,
            processed_mailbox=None,
        )
        assert result.ingested == 2  # оба обработаны (второе — дедуп-возврат)
        assert await _count_by_mid(session, mid) == 1  # но заявка одна

    _with_session(body)


def test_oversized_message_skipped_and_marked() -> None:
    mailbox = _FakeMailbox([_msg(body="это письмо заведомо длиннее крошечного лимита")])

    async def body(session: AsyncSession) -> None:
        result = await poll_and_ingest(
            session,
            mailbox,
            batch_limit=50,
            raw_max_bytes=10,  # любое реальное письмо больше
            attachment_max_bytes=_BIG,
            processed_mailbox=None,
        )
        assert result.ingested == 0
        assert result.skipped_oversized == 1
        assert len(mailbox.processed) == 1  # помечено, чтобы не было poison-перевыборки

    _with_session(body)


def test_ingest_failure_isolated_not_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сбой ingest одного письма не валит проход и НЕ помечает его обработанным (ретрай)."""

    async def flaky(session: AsyncSession, parsed: object, **kwargs: object) -> object:
        if getattr(parsed, "subject", None) == "FAIL":
            raise RuntimeError("boom")
        return await _real_ingest(session, parsed, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("api.email.worker.poll.ingest_email", flaky)
    fail_msg = _msg(subject="FAIL", body="сбойное")
    mailbox = _FakeMailbox([_msg(body="ок1"), fail_msg, _msg(body="ок2")])

    async def body(session: AsyncSession) -> None:
        result = await poll_and_ingest(
            session,
            mailbox,
            batch_limit=50,
            raw_max_bytes=_BIG,
            attachment_max_bytes=_BIG,
            processed_mailbox=None,
        )
        assert result.ingested == 2
        assert result.failed == 1
        processed_uids = {uid for uid, _ in mailbox.processed}
        assert fail_msg.uid not in processed_uids  # сбойное НЕ помечено → перевыберется

    _with_session(body)


def test_processed_mailbox_move_propagated() -> None:
    mailbox = _FakeMailbox([_msg(body="перенос")])

    async def body(session: AsyncSession) -> None:
        await poll_and_ingest(
            session,
            mailbox,
            batch_limit=50,
            raw_max_bytes=_BIG,
            attachment_max_bytes=_BIG,
            processed_mailbox="Processed",
        )
        assert mailbox.processed[0][1] == "Processed"  # move_to проброшен

    _with_session(body)


def test_actor_poll_inbox_connected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Actor с заданным imap_host подключается (фейк), принимает письма, закрывает ящик."""
    from api.email.worker import actor as actor_module

    mailbox = _FakeMailbox([_msg(body="через actor")])
    monkeypatch.setattr(get_settings(), "imap_host", "imap.example.test")
    # Патчим класс по его модулю-источнику — actor держит ссылку на тот же объект.
    monkeypatch.setattr(
        "api.email.worker.imap_client.ImaplibMailbox.connect",
        classmethod(lambda cls, settings: mailbox),
    )
    # Вызов actor'а напрямую гоняет _poll_once (asyncio.run внутри) — реальные engine/БД.
    actor_module.poll_inbox()
    assert len(mailbox.processed) == 1
    assert mailbox.closed is True


def test_extract_rfc822_helper() -> None:
    """imap_client._extract_rfc822 достаёт тело из ответа FETCH и игнорирует мету."""
    from api.email.worker.imap_client import _extract_rfc822

    assert _extract_rfc822([(b"1 (RFC822 {5}", b"hello"), b")"]) == b"hello"
    assert _extract_rfc822([b"no-payload"]) is None
    # base64 здесь только чтобы показать, что произвольные байты проходят как есть.
    payload = base64.b64encode(b"raw")
    assert _extract_rfc822([(b"meta", payload)]) == payload
