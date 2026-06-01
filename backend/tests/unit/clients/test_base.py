"""Тесты ResilientHttpClient (E3-2): timeout/retry/breaker/cache + graceful degradation.

httpx.MockTransport имитирует соседа; clock/sleep инжектируются (детерминизм)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from api.clients.base import ResilientHttpClient
from api.clients.cache import InMemoryCache
from api.clients.circuit_breaker import CircuitBreaker, CircuitState
from api.clients.errors import CircuitOpenError, ExternalServiceError
from api.clients.retry import RetryPolicy


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _noop_sleep(_: float) -> None:
    return None


_Handler = Callable[[httpx.Request], httpx.Response]


def _make(
    handler: _Handler,
    *,
    attempts: int = 3,
    threshold: int = 5,
    reset: float = 10.0,
    clock: _Clock | None = None,
) -> ResilientHttpClient:
    clock = clock or _Clock()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://svc")
    breaker = CircuitBreaker(failure_threshold=threshold, reset_timeout=reset, now=clock)
    return ResilientHttpClient(
        client_name="svc",
        http=http,
        breaker=breaker,
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )


async def test_success_returns_response() -> None:
    client = _make(lambda req: httpx.Response(200, json={"ok": True}))
    resp = await client.request("GET", "/x", operation="get_x")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_4xx_returned_without_exception() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client = _make(handler, attempts=3)
    resp = await client.request("GET", "/x", operation="get_x")
    assert resp.status_code == 404
    assert calls["n"] == 1  # 4xx не ретраится — сервис ответил


async def test_5xx_retried_then_external_error() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    client = _make(handler, attempts=3)
    with pytest.raises(ExternalServiceError) as ei:
        await client.request("GET", "/x", operation="get_x")
    assert ei.value.client == "svc"
    assert ei.value.operation == "get_x"
    assert calls["n"] == 3  # все попытки исчерпаны


async def test_transport_error_becomes_external_error() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    client = _make(handler, attempts=2)
    with pytest.raises(ExternalServiceError):
        await client.request("GET", "/x", operation="ping")
    assert calls["n"] == 2


async def test_circuit_opens_and_rejects_without_calling() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    # threshold=1, attempts=1: один сбойный вызов открывает breaker.
    client = _make(handler, attempts=1, threshold=1)
    with pytest.raises(ExternalServiceError):
        await client.request("GET", "/x", operation="op")
    assert calls["n"] == 1
    # Следующий вызов отклонён breaker'ом БЕЗ обращения к соседу.
    with pytest.raises(CircuitOpenError):
        await client.request("GET", "/x", operation="op")
    assert calls["n"] == 1


async def test_degradation_opens_after_threshold() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    clock = _Clock()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=30.0, now=clock)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://svc")
    client = ResilientHttpClient(
        client_name="svc",
        http=http,
        breaker=breaker,
        retry=RetryPolicy(attempts=1),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    for _ in range(2):
        with pytest.raises(ExternalServiceError):
            await client.request("GET", "/x", operation="op")
    assert breaker.state is CircuitState.OPEN


async def test_get_json_cache_aside() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"v": calls["n"]})

    client = _make(handler)
    cache = InMemoryCache(now=_Clock())

    first = await client.get_json(
        "/u/1", operation="get_user", cache=cache, cache_key="u:1", cache_ttl_seconds=60
    )
    assert first == {"v": 1}
    assert calls["n"] == 1

    # Второй вызов — попадание в кеш, соседа не дёргаем.
    second = await client.get_json(
        "/u/1", operation="get_user", cache=cache, cache_key="u:1", cache_ttl_seconds=60
    )
    assert second == {"v": 1}
    assert calls["n"] == 1


async def test_get_json_without_cache_always_fetches() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"v": calls["n"]})

    client = _make(handler)
    # Критичная операция без кеша — каждый раз свежий вызов (AT-003).
    await client.get_json("/c", operation="claim")
    await client.get_json("/c", operation="claim")
    assert calls["n"] == 2
