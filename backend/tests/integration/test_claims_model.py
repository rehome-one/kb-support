"""Integration-тесты claims-модели (E10-1 #191) — требуют Postgres.

claims-колонки на tickets (Numeric round-trip), TicketCaseDetails 1:1 (create/get/uniq/
ON DELETE CASCADE). Изоляция — откатываемая транзакция (патторн #165/#85). Миграция
up/down в общей :5433 НЕ гоняем (урок E4: ломает прочие ticket-тесты) — схема уже
мигрирована; проверяем поведение колонок/таблицы/констрейнтов.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import TypeVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.config import get_settings
from api.tickets.case_repository import TicketCaseDetailsRepository
from api.tickets.enums import ActKind, CaseType
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="claims-модель требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
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


def _ticket(idx: int, **kw: object) -> Ticket:
    return Ticket(
        number=f"RH-2001-{idx:05d}",
        subject="seed",
        description="seed",
        type=kw.pop("type", "COMPENSATION"),
        channel=kw.pop("channel", "LK_CLAIM"),
        status="OPEN",
        requester_id=uuid.uuid4(),
        created_at=datetime.datetime(2001, 1, 10, tzinfo=datetime.UTC),
        **kw,
    )


def test_claims_columns_persist_numeric_amounts() -> None:
    async def body(session: AsyncSession) -> None:
        t = _ticket(1, claim_amount=Decimal("12345.67"), case_state="CLAIM_SUBMITTED")
        session.add(t)
        await session.flush()
        await session.refresh(t)  # перечитать из БД (async-safe)
        assert t.claim_amount == Decimal("12345.67")  # точное хранение Numeric(14,2)
        assert t.case_state == "CLAIM_SUBMITTED"

    _in_rolled_back_session(body)


def test_case_details_create_and_get() -> None:
    async def body(session: AsyncSession) -> None:
        t = _ticket(2)
        session.add(t)
        await session.flush()
        repo = TicketCaseDetailsRepository(session)
        created = await repo.create(
            t.id,
            CaseType.ACCEPTANCE_ACT,
            act_kind=ActKind.MOVE_OUT,
            payload={"blocked_payment_id": "p1"},
        )
        assert created.case_type == "ACCEPTANCE_ACT"
        assert created.act_kind == "MOVE_OUT"
        fetched = await repo.get_by_ticket(t.id)
        assert fetched is not None and fetched.id == created.id
        assert fetched.payload == {"blocked_payment_id": "p1"}

    _in_rolled_back_session(body)


def test_case_details_unique_per_ticket() -> None:
    async def body(session: AsyncSession) -> None:
        t = _ticket(3)
        session.add(t)
        await session.flush()
        repo = TicketCaseDetailsRepository(session)
        await repo.create(t.id, CaseType.COMPENSATION)
        # Savepoint: IntegrityError откатит только вложенную транзакцию, не внешнюю.
        with pytest.raises(IntegrityError):  # uniq(ticket_id) — 1:1
            async with session.begin_nested():
                await repo.create(t.id, CaseType.COMPENSATION)

    _in_rolled_back_session(body)


def test_case_details_cascade_on_ticket_delete() -> None:
    async def body(session: AsyncSession) -> None:
        t = _ticket(4)
        session.add(t)
        await session.flush()
        repo = TicketCaseDetailsRepository(session)
        await repo.create(t.id, CaseType.INSURANCE)
        await session.execute(text("DELETE FROM tickets WHERE id = :id"), {"id": t.id})
        await session.flush()
        assert await repo.get_by_ticket(t.id) is None  # ON DELETE CASCADE

    _in_rolled_back_session(body)
