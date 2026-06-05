"""Integration-тесты репозитория шаблонов ответов (E6-1 #125) — требует Postgres.

Проверяет контракт репо для #126/#127/#128: list(+type-фильтр), get, create, update,
атомарный increment_usage. Синхронный (как test_sla_repository): свой NullPool-engine
внутри `asyncio.run` + rollback транзакции (изоляция, один event loop — избегаем
cross-loop teardown с asyncpg).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.canned.models import CannedResponse
from api.canned.repository import CannedResponseRepository
from api.config import get_settings

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Требует живой Postgres (CI service container или POSTGRES_AVAILABLE=1).",
)

T = TypeVar("T")


def _in_rolled_back_session(body: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Выполнить `body(session)` в транзакции, которая откатывается (изоляция)."""

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


def test_list_filters_by_type() -> None:
    token = uuid.uuid4().hex

    async def body(session: AsyncSession) -> tuple[list[str], list[str]]:
        session.add_all(
            [
                CannedResponse(title=f"fraud-{token}", body="b", type="FRAUD"),
                CannedResponse(title=f"payment-{token}", body="b", type="PAYMENT"),
                CannedResponse(title=f"notype-{token}", body="b", type=None),
            ]
        )
        await session.flush()
        repo = CannedResponseRepository(session)
        all_titles = [c.title for c in await repo.list() if token in c.title]
        fraud_titles = [c.title for c in await repo.list(type_filter="FRAUD") if token in c.title]
        return all_titles, fraud_titles

    all_titles, fraud_titles = _in_rolled_back_session(body)
    assert len(all_titles) == 3  # без фильтра — все три (мои)
    assert fraud_titles == [f"fraud-{token}"]  # фильтр по type=FRAUD


def test_get_and_update() -> None:
    async def body(session: AsyncSession) -> tuple[str, str | None]:
        repo = CannedResponseRepository(session)
        canned = await repo.create({"title": "t", "body": "old", "linked_article_slug": None})
        await repo.update(canned, {"body": "new", "linked_article_slug": "help/refund"})
        got = await repo.get(canned.id)
        assert got is not None
        return got.body, got.linked_article_slug

    body_text, slug = _in_rolled_back_session(body)
    assert body_text == "new"
    assert slug == "help/refund"


def test_increment_usage_is_atomic_and_reports_missing() -> None:
    async def body(session: AsyncSession) -> tuple[int, bool, bool]:
        repo = CannedResponseRepository(session)
        canned = await repo.create({"title": "t", "body": "b"})
        ok1 = await repo.increment_usage(canned.id)
        ok2 = await repo.increment_usage(canned.id)
        await session.refresh(canned)  # UPDATE минует ORM-атрибут — перечитать
        missing = await repo.increment_usage(uuid.uuid4())  # несуществующий id
        return canned.usage_count, (ok1 and ok2), missing

    count, ok, missing = _in_rolled_back_session(body)
    assert count == 2  # два инкремента
    assert ok is True  # оба нашли строку
    assert missing is False  # несуществующий id → False (best-effort у #128)
