"""Integration-тесты `GET /reports/{type}` (E8-3, #167) — требуют Postgres.

RBAC (supervisor→200 / operator→403 на ВСЕХ типах), 5 типов json, csv-формат, `from>to`→422,
неизвестный тип→422. Точные агрегаты — в `test_reports_aggregation`. Пустое окно (1990) →
детерминированная форма. Сессия — NullPool.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.auth.scopes import STAFF_SUPERVISOR_SCOPE, STAFF_SUPPORT_SCOPE
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Эндпоинт reports требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)

_EMPTY = {"from": "1990-01-01", "to": "1990-01-31"}
_TYPES = ["volume", "sla", "satisfaction", "reopens", "operators"]


def _principal(*scopes: str) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        scopes=frozenset(scopes),
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
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        import asyncio

        asyncio.run(engine.dispose())


@pytest.mark.parametrize("report_type", _TYPES)
def test_operator_forbidden_on_all_types(report_type: str) -> None:
    with _client(_principal(STAFF_SUPPORT_SCOPE)) as client:
        resp = client.get(f"/api/v1/support/reports/{report_type}", params=_EMPTY)
    assert resp.status_code == 403


@pytest.mark.parametrize("report_type", _TYPES)
def test_supervisor_gets_json_report(report_type: str) -> None:
    with _client(_principal(STAFF_SUPPORT_SCOPE, STAFF_SUPERVISOR_SCOPE)) as client:
        resp = client.get(f"/api/v1/support/reports/{report_type}", params=_EMPTY)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["report"] == report_type
    assert data["period"] == {"from": "1990-01-01", "to": "1990-01-31"}
    assert isinstance(data["rows"], list)


def test_csv_format_returns_text_csv() -> None:
    with _client(_principal(STAFF_SUPPORT_SCOPE, STAFF_SUPERVISOR_SCOPE)) as client:
        resp = client.get(
            "/api/v1/support/reports/satisfaction", params={**_EMPTY, "format": "csv"}
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().split("\n")
    assert lines[0] == "rating,count"
    assert len(lines) == 6  # header + 5 оценок (распределение 1..5)


def test_invalid_period_returns_422() -> None:
    with _client(_principal(STAFF_SUPERVISOR_SCOPE)) as client:
        resp = client.get(
            "/api/v1/support/reports/volume", params={"from": "2026-02-01", "to": "2026-01-01"}
        )
    assert resp.status_code == 422


def test_unknown_report_type_returns_422() -> None:
    with _client(_principal(STAFF_SUPERVISOR_SCOPE)) as client:
        resp = client.get("/api/v1/support/reports/nonsense", params=_EMPTY)
    assert resp.status_code == 422
