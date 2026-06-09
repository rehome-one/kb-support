"""Тесты клиента PaymentReleaseChecker (E10-7, #197): мягкая деградация → None.

httpx.MockTransport. 200+валид → Clearance; недоступность соседа (5xx/сеть), не-200,
битый JSON → None (информационна, не блокирует — ADR-0014 U4).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.payment_checker import Clearance, HttpPaymentReleaseCheckerClient
from api.clients.retry import RetryPolicy

_TICKET = uuid.UUID("33333333-3333-3333-3333-333333333333")


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 1
) -> HttpPaymentReleaseCheckerClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://checker")
    rc = ResilientHttpClient(
        client_name="payment_checker",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpPaymentReleaseCheckerClient(
        http_client=rc, token_provider=StaticTokenProvider("test-token")
    )


async def test_200_returns_clearance() -> None:
    client = _make(lambda req: httpx.Response(200, json={"clearable": True, "reason": None}))
    assert await client.check_clearance(_TICKET) == Clearance(clearable=True, reason=None)


async def test_200_not_clearable_with_reason() -> None:
    client = _make(lambda req: httpx.Response(200, json={"clearable": False, "reason": "hold"}))
    assert await client.check_clearance(_TICKET) == Clearance(clearable=False, reason="hold")


async def test_network_error_returns_none() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert await _make(_boom).check_clearance(_TICKET) is None


async def test_5xx_returns_none() -> None:
    assert await _make(lambda req: httpx.Response(503)).check_clearance(_TICKET) is None


async def test_404_returns_none() -> None:
    assert await _make(lambda req: httpx.Response(404)).check_clearance(_TICKET) is None


async def test_malformed_returns_none() -> None:
    client = _make(lambda req: httpx.Response(200, json={"wrong": "shape"}))
    assert await client.check_clearance(_TICKET) is None


# --- фабрика get_payment_release_checker_client (config-gate) ---


async def test_factory_disabled_yields_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.clients.payment_checker import deps
    from api.config import Settings

    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(payment_release_checker_api_token="")
    )
    async for client in deps.get_payment_release_checker_client():
        assert client is None


async def test_factory_enabled_yields_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.clients.payment_checker import HttpPaymentReleaseCheckerClient, deps
    from api.config import Settings

    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(
            payment_release_checker_api_token="m2m", payment_release_checker_api_base_url="http://c"
        ),
    )
    seen = [client async for client in deps.get_payment_release_checker_client()]
    assert len(seen) == 1
    assert isinstance(seen[0], HttpPaymentReleaseCheckerClient)
