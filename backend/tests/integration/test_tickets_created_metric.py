"""Integration: метрика `tickets_created_total` на создании заявок (E8-4, #168) — Postgres.

Дельты на 3 чокпоинтах (create / from-chat / from-email) + **идемпотентность** (повтор
from-chat той же chat_session_id НЕ задваивает счётчик, M1) + экспорт в /metrics.
"""

from __future__ import annotations

import base64
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Метрика создания требует живой Postgres (CI service / POSTGRES_AVAILABLE=1).",
)


def _count(ticket_type: str, channel: str) -> float:
    value = REGISTRY.get_sample_value(
        "tickets_created_total", {"type": ticket_type, "channel": channel}
    )
    return value or 0.0


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


_OPERATOR = Principal(
    user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({TicketTeam.SUPPORT})
)
_SERVICE = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.SERVICE)


def test_create_increments_counter() -> None:
    with _client(_OPERATOR) as client:
        # channel задаётся явно → измеряем тот же лейбл до и после (детерминизм).
        before = _count("MAINTENANCE", "INTERNAL")
        resp = client.post(
            "/api/v1/support/tickets",
            json={"subject": "m", "type": "MAINTENANCE", "channel": "INTERNAL"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["channel"] == "INTERNAL"
        assert _count("MAINTENANCE", "INTERNAL") == before + 1


def test_from_chat_idempotent_does_not_double_count() -> None:
    session_id = str(uuid.uuid4())
    payload = {
        "chat_session_id": session_id,
        "requester_id": str(uuid.uuid4()),
        "transcript": [{"role": "user", "content": "метрика"}],
    }
    with _client(_SERVICE) as client:
        before = _count("OTHER", "AI_CHAT")
        first = client.post("/api/v1/support/tickets/from-chat", json=payload)
        assert first.status_code == 201, first.text
        after_first = _count("OTHER", "AI_CHAT")
        assert after_first == before + 1
        # Повтор той же chat_session_id → возврат existing, БЕЗ инкремента (M1).
        second = client.post("/api/v1/support/tickets/from-chat", json=payload)
        assert second.status_code in (200, 201)
        assert _count("OTHER", "AI_CHAT") == after_first


def test_from_email_increments_counter() -> None:
    msg = EmailMessage()
    msg["From"] = "sender@example.com"
    msg["Subject"] = "metric email"
    msg["Message-ID"] = f"<{uuid.uuid4()}@mail>"
    msg.set_content("тело")
    raw = base64.b64encode(msg.as_bytes()).decode("ascii")
    with _client(_SERVICE) as client:
        before = _count("OTHER", "EMAIL")
        resp = client.post("/api/v1/support/tickets/from-email", json={"raw_message": raw})
        assert resp.status_code == 201, resp.text
        assert _count("OTHER", "EMAIL") == before + 1


def test_metric_exported_in_metrics_endpoint() -> None:
    with _client(_OPERATOR) as client:
        client.post("/api/v1/support/tickets", json={"subject": "x", "type": "ACCOUNT"})
        metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "tickets_created_total" in metrics.text
