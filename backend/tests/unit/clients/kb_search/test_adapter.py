"""Тесты клиента возврата ответа в kb-search (E3-4, #72): исходы, идемпотентность,
auth, ФЗ-152. httpx.MockTransport + инжектируемые clock/sleep (детерминизм)."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable
from unittest import mock

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_search import adapter as adapter_module
from api.clients.kb_search.adapter import HttpKbSearchClient
from api.clients.kb_search.models import OperatorReply, ReplyOutcome
from api.clients.retry import RetryPolicy

CHAT_SESSION_ID = uuid.uuid4()
TICKET_ID = uuid.uuid4()
MESSAGE_ID = uuid.uuid4()


def _reply(body: str = "Ответ оператора") -> OperatorReply:
    return OperatorReply(
        chat_session_id=CHAT_SESSION_ID,
        ticket_id=TICKET_ID,
        message_id=MESSAGE_ID,
        body=body,
        sent_at=datetime.datetime(2026, 6, 2, 10, 0, tzinfo=datetime.UTC),
    )


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    attempts: int = 2,
    threshold: int = 5,
    token: str = "test-token",
) -> HttpKbSearchClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://kb-search")
    rc = ResilientHttpClient(
        client_name="kb_search",
        http=http,
        breaker=CircuitBreaker(failure_threshold=threshold, reset_timeout=30.0, now=_Clock()),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpKbSearchClient(http_client=rc, token_provider=StaticTokenProvider(token))


async def test_202_delivered() -> None:
    client = _make(lambda req: httpx.Response(202))
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.DELIVERED


async def test_404_session_gone() -> None:
    client = _make(lambda req: httpx.Response(404))
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.SESSION_GONE


async def test_409_session_gone() -> None:
    client = _make(lambda req: httpx.Response(409))
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.SESSION_GONE


async def test_5xx_degraded() -> None:
    client = _make(lambda req: httpx.Response(503), attempts=2)
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.DEGRADED


async def test_other_4xx_degraded() -> None:
    client = _make(lambda req: httpx.Response(400))
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.DEGRADED


async def test_transport_error_degraded() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _make(handler, attempts=2)
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.DEGRADED


async def test_circuit_open_degraded() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    client = _make(handler, attempts=1, threshold=1)
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.DEGRADED  # открывает breaker
    assert await client.send_operator_reply(_reply()) is ReplyOutcome.DEGRADED  # circuit-open
    assert calls["n"] == 1  # второй раз соседа не дёргаем


async def test_body_and_headers() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        seen["auth"] = req.headers.get("authorization")
        seen["idem"] = req.headers.get("idempotency-key")
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(202)

    client = _make(handler, token="m2m-secret")
    await client.send_operator_reply(_reply(body="текст"))
    assert seen["auth"] == "Bearer m2m-secret"
    # Идемпотентность по message_id (ADR-0006 Решение 3).
    assert seen["idem"] == str(MESSAGE_ID)
    assert seen["path"] == f"/api/v1/chat/sessions/{CHAT_SESSION_ID}/operator-reply"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body == {
        "ticket_id": str(TICKET_ID),
        "message_id": str(MESSAGE_ID),
        "body": "текст",
        "author": "operator",
        "sent_at": "2026-06-02T10:00:00+00:00",
    }
    assert "attachments" not in body  # payload строго по контракту


async def test_message_body_not_logged() -> None:
    secret = "ПДн-в-теле-ответа-оператора"
    with mock.patch.object(adapter_module._logger, "warning") as warn:
        client = _make(lambda req: httpx.Response(404))  # SESSION_GONE → WARN
        assert await client.send_operator_reply(_reply(body=secret)) is ReplyOutcome.SESSION_GONE
    assert warn.called
    logged = " ".join(str(arg) for call in warn.call_args_list for arg in call.args)
    assert secret not in logged


# --- suggest_articles (E6-6, #130) ---


async def test_suggest_returns_articles() -> None:
    client = _make(
        lambda req: httpx.Response(
            200,
            json={"results": [{"slug": "help/a", "title": "Статья A", "url": "http://w/a"}]},
        )
    )
    out = await client.suggest_articles("оплата не прошла")
    assert out is not None
    assert [a.slug for a in out] == ["help/a"]
    assert out[0].title == "Статья A"


async def test_suggest_empty_results() -> None:
    client = _make(lambda req: httpx.Response(200, json={"results": []}))
    assert await client.suggest_articles("нет совпадений") == []


async def test_suggest_4xx_degrades_to_none() -> None:
    client = _make(lambda req: httpx.Response(500), attempts=1)
    assert await client.suggest_articles("x") is None


async def test_suggest_malformed_degrades_to_none() -> None:
    client = _make(lambda req: httpx.Response(200, json={"unexpected": 1}))
    assert await client.suggest_articles("x") is None


async def test_suggest_network_error_degrades_to_none() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _make(_boom, attempts=1)
    assert await client.suggest_articles("x") is None
