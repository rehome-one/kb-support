"""Unit-тесты проброса request_id (middleware + ответный заголовок)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from api.main import app
from api.observability.context import request_id_var
from api.observability.request_id import RequestIdMiddleware


def test_generates_request_id_when_absent() -> None:
    with TestClient(app) as client:
        resp = client.get("/healthz")
    # Сгенерирован валидный uuid и проброшен в ответ.
    uuid.UUID(resp.headers["x-request-id"])


def test_propagates_incoming_request_id() -> None:
    with TestClient(app) as client:
        resp = client.get("/healthz", headers={"X-Request-Id": "trace-abc-1"})
    assert resp.headers["x-request-id"] == "trace-abc-1"


@pytest.mark.asyncio
async def test_middleware_sets_contextvar_and_header() -> None:
    captured: dict[str, str | None] = {}

    async def _dummy_app(scope: Scope, receive: Receive, send: Send) -> None:
        captured["rid"] = request_id_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent: list[Message] = []

    async def _send(message: Message) -> None:
        sent.append(message)

    async def _receive() -> Message:
        return {"type": "http.request"}

    middleware = RequestIdMiddleware(_dummy_app)
    await middleware({"type": "http", "headers": [(b"x-request-id", b"trace-9")]}, _receive, _send)

    assert captured["rid"] == "trace-9"
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert (b"x-request-id", b"trace-9") in start["headers"]
    # Контекст сброшен после запроса.
    assert request_id_var.get() is None
