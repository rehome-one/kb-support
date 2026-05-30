"""Тесты readiness-пробы /readyz (#13)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.config import get_settings
from api.db import get_session
from api.main import app

requires_postgres = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="readyz=200 требует живой Postgres (CI/POSTGRES_AVAILABLE)",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_session, None)


@requires_postgres
def test_readyz_returns_200_when_db_up(client: TestClient) -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    try:
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
    finally:
        asyncio.run(engine.dispose())


def test_readyz_returns_503_when_db_unavailable(client: TestClient) -> None:
    class _FailingSession:
        async def execute(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("database unreachable")

    async def _session() -> AsyncIterator[_FailingSession]:
        yield _FailingSession()

    app.dependency_overrides[get_session] = _session
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"


def test_healthz_unaffected_by_db() -> None:
    """Liveness не зависит от БД (в отличие от readiness)."""

    async def _session() -> AsyncIterator[Any]:
        raise RuntimeError("should not be called")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = _session
    try:
        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200
    finally:
        app.dependency_overrides.pop(get_session, None)
