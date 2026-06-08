"""Integration-тесты `GET /support/stats` (E8-2, #166) — требуют Postgres.

RBAC (supervisor→200 / operator→403), невалидный период→422, containment-seam
(выключено→degraded; клиент→rate). Точные агрегаты покрыты в `test_analytics_aggregation`
(#165); здесь — поведение эндпоинта. Кэш переопределён на InMemory (без Redis в тесте),
сессия — NullPool (cross-loop). Период берём пустой (1990) → детерминированная форма.
"""

from __future__ import annotations

import datetime
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.analytics.deps import get_analytics_cache
from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.auth.scopes import STAFF_SUPERVISOR_SCOPE, STAFF_SUPPORT_SCOPE
from api.clients.cache import InMemoryCache
from api.clients.kb_search.deps import get_kb_search_client
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Эндпоинт stats требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

_EMPTY = {"from": "1990-01-01", "to": "1990-01-31"}


def _supervisor() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        scopes=frozenset({STAFF_SUPPORT_SCOPE, STAFF_SUPERVISOR_SCOPE}),
        teams=frozenset({TicketTeam.SUPPORT}),
    )


def _operator() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        scopes=frozenset({STAFF_SUPPORT_SCOPE}),
        teams=frozenset({TicketTeam.SUPPORT}),
    )


class _FakeKbSearch:
    """kb-search клиент, возвращающий фиксированный containment (для не-degraded ветки)."""

    def __init__(self, rate: float) -> None:
        self._rate = rate

    async def get_containment_stats(
        self, period_from: datetime.date, period_to: datetime.date
    ) -> float | None:
        return self._rate


@contextmanager
def _client(principal: Principal, *, kb_search: object | None = None) -> Iterator[TestClient]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session() -> object:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_analytics_cache] = lambda: InMemoryCache(now=time.monotonic)
    app.dependency_overrides[get_kb_search_client] = lambda: kb_search
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        import asyncio

        asyncio.run(engine.dispose())


def test_operator_without_supervisor_scope_forbidden() -> None:
    with _client(_operator()) as client:
        resp = client.get("/api/v1/support/stats", params=_EMPTY)
    assert resp.status_code == 403


def test_supervisor_gets_stats_degraded_when_kb_search_off() -> None:
    with _client(_supervisor(), kb_search=None) as client:
        resp = client.get("/api/v1/support/stats", params=_EMPTY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["period"] == {"from": "1990-01-01", "to": "1990-01-31"}
    # Пустой период → нулевой знаменатель → null/0 (инвариант ядра #165).
    assert data["sla"]["resolution_compliance_pct"] is None
    assert data["tickets"]["total"] == 0
    # kb-search выключен → containment недоступен.
    assert data["ai_chat"]["containment_rate_pct"] is None
    assert data["ai_chat"]["degraded"] is True
    assert data["ai_chat"]["escalated_count"] == 0


def test_supervisor_gets_containment_when_kb_search_available() -> None:
    with _client(_supervisor(), kb_search=_FakeKbSearch(81.0)) as client:
        resp = client.get("/api/v1/support/stats", params=_EMPTY)
    assert resp.status_code == 200
    ai_chat = resp.json()["data"]["ai_chat"]
    assert ai_chat["containment_rate_pct"] == 81.0
    assert ai_chat["degraded"] is False


def test_invalid_period_from_after_to_returns_422() -> None:
    with _client(_supervisor()) as client:
        resp = client.get(
            "/api/v1/support/stats", params={"from": "2026-02-01", "to": "2026-01-01"}
        )
    assert resp.status_code == 422


def test_default_period_when_no_params() -> None:
    with _client(_supervisor(), kb_search=None) as client:
        resp = client.get("/api/v1/support/stats")
    assert resp.status_code == 200
    period = resp.json()["data"]["period"]
    # Дефолт — 30-дневное окно (from < to).
    assert period["from"] < period["to"]
