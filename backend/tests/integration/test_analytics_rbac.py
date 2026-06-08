"""RBAC-матрица аналитики (E8-8, #172) — добор после #166/#167. Требует Postgres.

Существующие тесты пиннят operator(staff_support)→403 и supervisor(оба scope)→200.
Здесь добираем края матрицы (решение ADR-0011/#164: аналитика требует СТРОГО
`is_staff_supervisor`, не выводится из staff_support и не требует его):
- принципал БЕЗ scope'ов → 403 на `/stats` и всех 5 `/reports`;
- принципал ТОЛЬКО `staff_supervisor` (без `staff_support`) → 200 (тело отчёта),
  доказывая, что доступ к аналитике не зависит от наличия staff_support.

DB-запись не нужна (пустое окно 1990); сессия — на всякий случай, как в `test_stats_endpoint`.
"""

from __future__ import annotations

import asyncio
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
from api.auth.scopes import STAFF_SUPERVISOR_SCOPE
from api.clients.cache import InMemoryCache
from api.clients.kb_search.deps import get_kb_search_client
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="RBAC аналитики требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

_EMPTY = {"from": "1990-01-01", "to": "1990-01-31"}
_REPORT_TYPES = ["volume", "sla", "satisfaction", "reopens", "operators"]


def _no_scope() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        scopes=frozenset(),
        teams=frozenset({TicketTeam.SUPPORT}),
    )


def _supervisor_only() -> Principal:
    """Только staff_supervisor, БЕЗ staff_support — проверяет независимость аналитики."""
    return Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        scopes=frozenset({STAFF_SUPERVISOR_SCOPE}),
        teams=frozenset({TicketTeam.SUPPORT}),
    )


@contextmanager
def _client(principal: Principal) -> Iterator[TestClient]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session() -> object:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_analytics_cache] = lambda: InMemoryCache(now=time.monotonic)
    app.dependency_overrides[get_kb_search_client] = lambda: None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_no_scope_forbidden_on_stats() -> None:
    with _client(_no_scope()) as client:
        resp = client.get("/api/v1/support/stats", params=_EMPTY)
    assert resp.status_code == 403


@pytest.mark.parametrize("report_type", _REPORT_TYPES)
def test_no_scope_forbidden_on_all_reports(report_type: str) -> None:
    with _client(_no_scope()) as client:
        resp = client.get(f"/api/v1/support/reports/{report_type}", params=_EMPTY)
    assert resp.status_code == 403


def test_supervisor_only_allowed_on_stats() -> None:
    # staff_supervisor без staff_support → 200 (доступ к аналитике от staff_support не зависит).
    with _client(_supervisor_only()) as client:
        resp = client.get("/api/v1/support/stats", params=_EMPTY)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["period"] == {"from": "1990-01-01", "to": "1990-01-31"}


@pytest.mark.parametrize("report_type", _REPORT_TYPES)
def test_supervisor_only_allowed_on_all_reports(report_type: str) -> None:
    with _client(_supervisor_only()) as client:
        resp = client.get(f"/api/v1/support/reports/{report_type}", params=_EMPTY)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["report"] == report_type
