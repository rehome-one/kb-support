"""Тесты клиента страховщика (E10-10 PR-B #200): мутация → raise (как bank)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.errors import ExternalServiceError
from api.clients.insurer import HttpInsurerClient, InsurerEvent
from api.clients.retry import RetryPolicy

_TICKET = uuid.UUID("55555555-5555-5555-5555-555555555555")
_EVENT = InsurerEvent(ticket_id=_TICKET, insurance_event_id=uuid.uuid4())


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 1
) -> HttpInsurerClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://insurer")
    rc = ResilientHttpClient(
        client_name="insurer",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpInsurerClient(http_client=rc, token_provider=StaticTokenProvider("test-token"))


async def test_202_ok() -> None:
    seen: dict[str, object] = {}

    def _handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = req.content
        return httpx.Response(202)

    await _make(_handler).send_event(_EVENT)  # не бросает
    assert seen["path"] == "/api/v1/events"
    assert b"ticket_id" in seen["body"]  # type: ignore[operator]


async def test_4xx_raises() -> None:
    with pytest.raises(ExternalServiceError):
        await _make(lambda req: httpx.Response(422)).send_event(_EVENT)


async def test_network_error_raises() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ExternalServiceError):
        await _make(_boom).send_event(_EVENT)


async def test_none_insurance_event_id_serialized_null() -> None:
    seen: dict[str, bytes] = {}

    def _handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = req.content
        return httpx.Response(202)

    await _make(_handler).send_event(InsurerEvent(ticket_id=_TICKET, insurance_event_id=None))
    assert (
        b'"insurance_event_id": null' in seen["body"]
        or b'"insurance_event_id":null' in seen["body"]
    )
