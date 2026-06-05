"""Тесты клиента kb-wiki (E6-5, #129): 3-state article_exists, деградация, auth.

httpx.MockTransport + инжектируемые clock/sleep (детерминизм). 200→True, 404→False
(подтверждённо нет), 5xx/прочее/сетевой сбой→None (деградация AT-003)."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_wiki.adapter import HttpKbWikiClient
from api.clients.retry import RetryPolicy


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 2
) -> HttpKbWikiClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://kb-wiki")
    rc = ResilientHttpClient(
        client_name="kb_wiki",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpKbWikiClient(http_client=rc, token_provider=StaticTokenProvider("test-token"))


async def test_200_exists() -> None:
    client = _make(lambda req: httpx.Response(200, json={"slug": "help/x"}))
    assert await client.article_exists("help/x") is True


async def test_404_confirmed_absent() -> None:
    client = _make(lambda req: httpx.Response(404))
    assert await client.article_exists("nope") is False


async def test_5xx_degrades_to_none() -> None:
    client = _make(lambda req: httpx.Response(500), attempts=1)
    assert await client.article_exists("x") is None


async def test_network_error_degrades_to_none() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _make(_boom, attempts=1)
    assert await client.article_exists("x") is None


async def test_sends_bearer_token() -> None:
    seen: dict[str, str] = {}

    def _handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("Authorization", "")
        return httpx.Response(200, json={})

    client = _make(_handler)
    await client.article_exists("help/x")
    assert seen["auth"] == "Bearer test-token"
