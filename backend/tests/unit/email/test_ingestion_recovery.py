"""Unit-тесты recovery-ветки ingestion (E7-3, #145) — гонка на частичном uniq
`email_message_id`.

Без Postgres: методы `TicketRepository` замоканы так, чтобы pre-check дедупа
«промахнулся» (как в окне гонки), а последующий `add_email_message.flush` бросил
`IntegrityError`. Проверяется оркестрация `_recover_dedup`: откат транзакции →
поиск победителя по `find_message_by_email_id` (НЕ по `find_active_by_number`,
условие m3) → возврат его заявки с `deduped=True`. Реальную конкурентную вставку
этот путь требует двух закоммиченных транзакций (см. integration-фикстуру —
один откатываемый tx такого не воспроизводит без засорения общей тест-БД).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from api.email.ingestion import IngestResult, ingest_email
from api.email.parser import ParsedEmail
from api.tickets.messages import TicketMessage
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository


def _parsed(*, message_id: str | None, ticket_number: str | None) -> ParsedEmail:
    return ParsedEmail(
        from_addr="sender@example.com",
        message_id=message_id,
        subject="тема",
        text_body="тело",
        ticket_number=ticket_number,
        attachments=(),
        oversized_filenames=(),
        date=None,
        in_reply_to=None,
        references=(),
        parse_error=None,
    )


class _FakeSession:
    """Минимальная сессия для recovery: считает откаты, отдаёт заявку победителя."""

    def __init__(self, winner: Ticket) -> None:
        self._winner = winner
        self.rolled_back = 0

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def get(self, model: type[Ticket], pk: uuid.UUID) -> Ticket:
        return self._winner


def _patch_repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    winner_message: TicketMessage,
    target: Ticket | None,
    new_ticket: Ticket,
) -> None:
    """Замокать репозиторий: pre-check дедупа промахивается (None при 1-м вызове),
    recovery-поиск находит победителя; add_email_message всегда бросает IntegrityError."""
    calls = {"find_by_email": 0}

    async def flaky_find_by_email(
        self: TicketRepository, email_message_id: str
    ) -> TicketMessage | None:
        calls["find_by_email"] += 1
        # 1-й вызов = pre-check (окно гонки, ещё не видно) → None; далее = recovery.
        return None if calls["find_by_email"] == 1 else winner_message

    async def find_active(self: TicketRepository, number: str) -> Ticket | None:
        return target

    async def create_from_email(self: TicketRepository, **kwargs: object) -> Ticket:
        return new_ticket

    async def raise_integrity(
        self: TicketRepository, *args: object, **kwargs: object
    ) -> TicketMessage:
        raise IntegrityError("INSERT INTO ticket_messages", {}, Exception("duplicate key"))

    monkeypatch.setattr(TicketRepository, "find_message_by_email_id", flaky_find_by_email)
    monkeypatch.setattr(TicketRepository, "find_active_by_number", find_active)
    monkeypatch.setattr(TicketRepository, "create_from_email", create_from_email)
    monkeypatch.setattr(TicketRepository, "add_email_message", raise_integrity)


@pytest.mark.asyncio
async def test_recover_dedup_on_new_ticket_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Создание новой заявки проигрывает гонку на uniq → откат + возврат победителя."""
    winner = Ticket(id=uuid.uuid4())
    winner_message = TicketMessage(ticket_id=winner.id)
    session = _FakeSession(winner)
    _patch_repo(
        monkeypatch, winner_message=winner_message, target=None, new_ticket=Ticket(id=uuid.uuid4())
    )

    result = await ingest_email(
        session,  # type: ignore[arg-type]  # FakeSession реализует нужный минимум
        _parsed(message_id="<race@mail>", ticket_number=None),
        platform_client=None,
        kb_files_client=None,
    )

    assert isinstance(result, IngestResult)
    assert result.deduped is True
    assert result.created is False
    assert result.ticket.id == winner.id  # возвращён победитель, не наша заявка
    assert session.rolled_back == 1  # транзакция откачена (наша заявка отброшена)


@pytest.mark.asyncio
async def test_recover_dedup_on_reply_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ к активной заявке тоже проигрывает гонку → откат + возврат победителя."""
    active = Ticket(id=uuid.uuid4())
    winner = Ticket(id=uuid.uuid4())
    winner_message = TicketMessage(ticket_id=winner.id)
    session = _FakeSession(winner)
    _patch_repo(
        monkeypatch,
        winner_message=winner_message,
        target=active,
        new_ticket=Ticket(id=uuid.uuid4()),
    )

    result = await ingest_email(
        session,  # type: ignore[arg-type]
        _parsed(message_id="<race@mail>", ticket_number="RH-2026-00001"),
        platform_client=None,
        kb_files_client=None,
    )

    assert result.deduped is True
    assert result.ticket.id == winner.id
    assert session.rolled_back == 1
