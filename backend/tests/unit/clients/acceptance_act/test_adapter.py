"""Тесты клиента AcceptanceAct (E10-9 PR-A, #199): мягкая деградация → None.

httpx.MockTransport. 200+валид → AcceptanceAct (вкл. damage_amount как Decimal); недоступность
соседа (5xx/сеть), не-200, битый JSON → None (мягкая, как PaymentReleaseChecker, ADR-0016).
"""

from __future__ import annotations

import decimal
import uuid
from collections.abc import Callable

import httpx

from api.clients.acceptance_act import AcceptanceAct, HttpAcceptanceActClient
from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.retry import RetryPolicy

_ACT = uuid.UUID("44444444-4444-4444-4444-444444444444")


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 1
) -> HttpAcceptanceActClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://acts")
    rc = ResilientHttpClient(
        client_name="acceptance_act",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpAcceptanceActClient(http_client=rc, token_provider=StaticTokenProvider("test-token"))


async def test_200_returns_act_with_damage() -> None:
    client = _make(
        lambda req: httpx.Response(
            200,
            json={
                "id": str(_ACT),
                "kind": "MOVE_OUT",
                "signing_status": "both_signed",
                "damage_amount": "12000.50",
            },
        )
    )
    act = await client.get_act(_ACT)
    assert act == AcceptanceAct(
        id=str(_ACT),
        kind="MOVE_OUT",
        signing_status="both_signed",
        damage_amount=decimal.Decimal("12000.50"),
    )


async def test_200_no_damage_is_none() -> None:
    client = _make(
        lambda req: httpx.Response(
            200, json={"id": str(_ACT), "kind": "MOVE_IN", "signing_status": "one_signed"}
        )
    )
    act = await client.get_act(_ACT)
    assert act is not None
    assert act.damage_amount is None
    assert act.kind == "MOVE_IN"


async def test_path_carries_act_id() -> None:
    seen: dict[str, str] = {}

    def _handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        return httpx.Response(
            200, json={"id": str(_ACT), "kind": "MOVE_IN", "signing_status": "one_signed"}
        )

    await _make(_handler).get_act(_ACT)
    assert seen["path"] == f"/api/v1/acts/{_ACT}"


async def test_network_error_returns_none() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert await _make(_boom).get_act(_ACT) is None


async def test_non_200_returns_none() -> None:
    assert await _make(lambda req: httpx.Response(404)).get_act(_ACT) is None


async def test_5xx_degrades_to_none() -> None:
    assert await _make(lambda req: httpx.Response(503), attempts=2).get_act(_ACT) is None


async def test_malformed_json_returns_none() -> None:
    client = _make(lambda req: httpx.Response(200, json={"kind": "MOVE_OUT"}))  # нет id/signing
    assert await client.get_act(_ACT) is None


async def test_malformed_damage_returns_none() -> None:
    client = _make(
        lambda req: httpx.Response(
            200,
            json={
                "id": str(_ACT),
                "kind": "MOVE_OUT",
                "signing_status": "both_signed",
                "damage_amount": "not-a-number",
            },
        )
    )
    assert await client.get_act(_ACT) is None  # decimal.InvalidOperation → None
