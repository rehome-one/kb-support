"""Integration-тест скана time_based-правил (#110) — требует Postgres.

Проверяет РЕАЛЬНЫЙ SQL-предикат выборки против живой БД (то, что unit на компиляции не
ловит): применение действий, дедуп через `updated_at`, ветку unanswered, исключение
терминальных, согласованность чистого зеркала с SQL-клаузой, фильтр `statuses` на
on_update (через run_rules), no-silent-caps WARN при насыщении.

Тест-БД общая (заявки/правила накапливаются). Изоляция от накопленных данных:
- правило таргетируется уникальным keyword'ом в subject заявки → чужие накопленные
  правила мою заявку не трогают, моё правило — только мою заявку;
- скан-ассерты используют БОЛЬШОЙ batch_limit, иначе накопленные старые заявки вытеснят
  мою (свежий `updated_at`) за лимит при `ORDER BY updated_at asc` (на чистой CI-БД лимит
  неважен);
- согласованность SQL↔зеркало проверяется на запросе, СУЖЕННОМ до моих id (без batch).
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.automation import time_based
from api.automation.engine import run_rules
from api.automation.models import AutomationRule
from api.automation.time_based import (
    scan_time_based,
    time_predicate_clause,
    time_predicate_satisfied,
)
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketStatus, TicketTeam
from api.tickets.models import Ticket

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Скан time_based требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

UTC = datetime.UTC
_FAR_PAST = datetime.datetime(2000, 1, 1, tzinfo=UTC)
# Большой лимит: на накопленной локальной БД защищает целевую заявку от усечения
# (ORDER BY updated_at asc). На чистой CI-БД значение неважно.
_BIG_BATCH = 1_000_000

_OPERATOR = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)


@pytest.fixture
def factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)

    async def _get_test_session() -> AsyncIterator[AsyncSession]:
        async with async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _get_test_session
    app.dependency_overrides[get_current_principal] = lambda: _OPERATOR
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_principal, None)
    asyncio.run(engine.dispose())


def _create_ticket(client: TestClient, subject: str) -> uuid.UUID:
    resp = client.post("/api/v1/support/tickets", json={"subject": subject, "type": "OTHER"})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["data"]["id"])


def _rule(token: str, conditions: dict[str, object], tag: str, **over: object) -> AutomationRule:
    return AutomationRule(
        name=f"rule-{token}",
        trigger="time_based",
        conditions=conditions,
        actions=[{"action": "add_tag", "params": {"tags": [tag]}}],
        is_active=True,
        apply_order=0,
        **over,
    )


def test_scan_applies_action_and_dedups_via_updated_at(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    token = f"tb-{uuid.uuid4().hex}"
    tag = f"stale-{token}"
    with TestClient(app) as client:
        ticket_id = _create_ticket(client, subject=f"тема {token}")

    async def _run() -> tuple[bool, datetime.datetime, bool, datetime.datetime]:
        now = datetime.datetime.now(UTC)
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            ticket.status = TicketStatus.PENDING.value
            ticket.updated_at = _FAR_PAST  # давно без активности
            session.add(
                _rule(
                    token,
                    {"statuses": ["PENDING"], "keywords": [token], "inactive_minutes": 1},
                    tag,
                )
            )
            await session.commit()

        # 1-й проход: заявка давно неактивна → действие применяется.
        async with factory() as session:
            await scan_time_based(session, now=now, batch_limit=_BIG_BATCH)
            await session.commit()

        async with factory() as session:
            t1 = await session.get(Ticket, ticket_id)
            assert t1 is not None
            applied = tag in (t1.tags or [])
            ua1 = t1.updated_at  # обновлён действием (дедуп-анкор)

        # 2-й проход: now чуть позже свежего updated_at, но в пределах inactive → НЕ выбирается.
        now2 = ua1 + datetime.timedelta(seconds=30)
        async with factory() as session:
            await scan_time_based(session, now=now2, batch_limit=_BIG_BATCH)
            await session.commit()

        async with factory() as session:
            t2 = await session.get(Ticket, ticket_id)
            assert t2 is not None
            return applied, ua1, (tag in (t2.tags or [])), t2.updated_at

    applied, ua1, still_tagged, ua2 = asyncio.run(_run())
    assert applied is True  # действие применено на 1-м проходе
    assert still_tagged is True  # тег на месте
    assert ua2 == ua1  # дедуп: 2-й проход НЕ тронул заявку (updated_at не изменился)


def test_scan_unanswered_branch_applies(factory: async_sessionmaker[AsyncSession]) -> None:
    token = f"tb-{uuid.uuid4().hex}"
    tag = f"nofr-{token}"
    with TestClient(app) as client:
        ticket_id = _create_ticket(client, subject=f"тема {token}")

    async def _run() -> bool:
        now = datetime.datetime.now(UTC)
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            ticket.status = TicketStatus.OPEN.value
            ticket.first_responded_at = None  # без первого ответа
            ticket.created_at = _FAR_PAST  # создана давно
            session.add(_rule(token, {"keywords": [token], "unanswered_minutes": 1}, tag))
            await session.commit()

        async with factory() as session:
            await scan_time_based(session, now=now, batch_limit=_BIG_BATCH)
            await session.commit()

        async with factory() as session:
            t = await session.get(Ticket, ticket_id)
            assert t is not None
            return tag in (t.tags or [])

    assert asyncio.run(_run()) is True


def test_scan_excludes_terminal(factory: async_sessionmaker[AsyncSession]) -> None:
    token = f"tb-{uuid.uuid4().hex}"
    tag = f"term-{token}"
    with TestClient(app) as client:
        ticket_id = _create_ticket(client, subject=f"тема {token}")

    async def _run() -> bool:
        now = datetime.datetime.now(UTC)
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            ticket.status = TicketStatus.RESOLVED.value  # терминальный
            ticket.updated_at = _FAR_PAST
            session.add(_rule(token, {"keywords": [token], "inactive_minutes": 1}, tag))
            await session.commit()

        async with factory() as session:
            await scan_time_based(session, now=now, batch_limit=_BIG_BATCH)
            await session.commit()

        async with factory() as session:
            t = await session.get(Ticket, ticket_id)
            assert t is not None
            return tag in (t.tags or [])

    assert asyncio.run(_run()) is False  # терминальная заявка не сканируется


def test_sql_clause_matches_pure_mirror(factory: async_sessionmaker[AsyncSession]) -> None:
    """Условие ревью 2 (MAJOR): SQL-клауза и чистое зеркало согласованы на одном наборе.

    Запрос сужен до моих id (без batch) — изоляция от накопленных данных; проверяется
    именно эквивалентность предиката, не механика выборки/усечения."""
    token = f"tb-{uuid.uuid4().hex}"
    with TestClient(app) as client:
        old_id = _create_ticket(client, subject=f"old {token}")
        fresh_id = _create_ticket(client, subject=f"fresh {token}")

    async def _run() -> None:
        now = datetime.datetime.now(UTC)
        conditions: dict[str, object] = {"inactive_minutes": 60}
        async with factory() as session:
            old = await session.get(Ticket, old_id)
            fresh = await session.get(Ticket, fresh_id)
            assert old is not None and fresh is not None
            old.status = TicketStatus.OPEN.value
            old.updated_at = now - datetime.timedelta(minutes=60)  # ровно на границе
            fresh.status = TicketStatus.OPEN.value
            fresh.updated_at = now - datetime.timedelta(minutes=30)  # свежее границы
            await session.commit()

        async with factory() as session:
            stmt = select(Ticket.id).where(
                Ticket.id.in_([old_id, fresh_id]), time_predicate_clause(conditions, now)
            )
            sql_ids = set((await session.execute(stmt)).scalars().all())
            for tid in (old_id, fresh_id):
                t = await session.get(Ticket, tid)
                assert t is not None
                mirror = time_predicate_satisfied(t, conditions, now)
                assert (tid in sql_ids) == mirror, f"расхождение SQL↔зеркало для {tid}"

        assert old_id in sql_ids  # граница `<=` включительна
        assert fresh_id not in sql_ids

    asyncio.run(_run())


def test_batch_saturation_warns(factory: async_sessionmaker[AsyncSession]) -> None:
    """No silent caps (условие ревью 7): при насыщении batch_limit — WARNING.

    Логгер api.* имеет propagate=False (урок #71) → мокаем `_logger.warning`, а не caplog.
    batch_limit=1 + ≥1 подходящая заявка → выборка насыщена → предупреждение."""
    token = f"tb-{uuid.uuid4().hex}"
    tag = f"sat-{token}"
    with TestClient(app) as client:
        ticket_id = _create_ticket(client, subject=f"тема {token}")

    async def _run() -> None:
        now = datetime.datetime.now(UTC)
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            ticket.status = TicketStatus.OPEN.value
            ticket.updated_at = _FAR_PAST  # старейшая → попадёт в batch=1 первой
            session.add(_rule(token, {"keywords": [token], "inactive_minutes": 1}, tag))
            await session.commit()

        async with factory() as session:
            await scan_time_based(session, now=now, batch_limit=1)
            await session.commit()

    with mock.patch.object(time_based._logger, "warning") as warn:
        asyncio.run(_run())
    assert warn.called  # насыщение → WARN (хотя бы один проход правила с len==limit)


def test_statuses_dimension_filters_on_update(factory: async_sessionmaker[AsyncSession]) -> None:
    """Условие ревью 6: расширение statuses работает и для on_update (через run_rules)."""
    token = f"tb-{uuid.uuid4().hex}"
    tag_match = f"st-match-{token}"
    tag_miss = f"st-miss-{token}"
    with TestClient(app) as client:
        ticket_id = _create_ticket(client, subject=f"тема {token}")

    async def _run() -> tuple[bool, bool]:
        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            ticket.status = TicketStatus.OPEN.value
            session.add_all(
                [
                    AutomationRule(
                        name=f"miss-{token}",
                        trigger="on_update",
                        conditions={"keywords": [token], "statuses": ["PENDING"]},  # ≠ OPEN
                        actions=[{"action": "add_tag", "params": {"tags": [tag_miss]}}],
                        is_active=True,
                        apply_order=0,
                    ),
                    AutomationRule(
                        name=f"match-{token}",
                        trigger="on_update",
                        conditions={"keywords": [token], "statuses": ["OPEN"]},  # = OPEN
                        actions=[{"action": "add_tag", "params": {"tags": [tag_match]}}],
                        is_active=True,
                        apply_order=1,
                    ),
                ]
            )
            await session.commit()

        async with factory() as session:
            ticket = await session.get(Ticket, ticket_id)
            assert ticket is not None
            await run_rules(session, ticket, "on_update")
            await session.commit()

        async with factory() as session:
            t = await session.get(Ticket, ticket_id)
            assert t is not None
            tags = t.tags or []
            return (tag_match in tags, tag_miss in tags)

    matched, missed = asyncio.run(_run())
    assert matched is True  # statuses=[OPEN] совпал → применён
    assert missed is False  # statuses=[PENDING] не совпал → не применён
