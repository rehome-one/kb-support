"""Тесты клиента BankProvider (E10-7, #197): release_payout, raise-деградация, no-PII.

httpx.MockTransport. 2xx+валид → PayoutResult; недоступность соседа (5xx/сеть) →
ExternalServiceError (база #70); 4xx и битый JSON → raise (мутация, ADR-0010 Реш.4 —
типизированная ошибка, НЕ None). Суммы/ПДн НЕ попадают в логи/текст исключения.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal
from unittest import mock

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.bank import PayoutRequest, PayoutResult
from api.clients.bank import adapter as adapter_module
from api.clients.bank.adapter import HttpBankProviderClient
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.errors import ExternalServiceError
from api.clients.retry import RetryPolicy

_TICKET = uuid.UUID("22222222-2222-2222-2222-222222222222")


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 2
) -> HttpBankProviderClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://bank")
    rc = ResilientHttpClient(
        client_name="bank",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpBankProviderClient(http_client=rc, token_provider=StaticTokenProvider("test-token"))


def _request() -> PayoutRequest:
    return PayoutRequest(
        ticket_id=_TICKET, amount=Decimal("12345.67"), currency="RUB", reference="RH-2026-00042"
    )


async def test_202_returns_payout_result() -> None:
    client = _make(lambda req: httpx.Response(202, json={"payment_id": "pay-abc"}))
    result = await client.release_payout(_request())
    assert result == PayoutResult(payment_id="pay-abc")


async def test_sends_amount_as_string_and_bearer() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["auth"] = req.headers.get("Authorization")
        import json as _json

        captured["body"] = _json.loads(req.content)
        return httpx.Response(202, json={"payment_id": "p1"})

    await _make(_h).release_payout(_request())
    assert captured["auth"] == "Bearer test-token"
    assert captured["body"] == {
        "ticket_id": str(_TICKET),
        "amount": "12345.67",  # точная строка, без float
        "currency": "RUB",
        "reference": "RH-2026-00042",
    }


async def test_network_error_propagates() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ExternalServiceError):
        await _make(_boom, attempts=1).release_payout(_request())


async def test_5xx_propagates() -> None:
    with pytest.raises(ExternalServiceError):
        await _make(lambda req: httpx.Response(503), attempts=1).release_payout(_request())


async def test_4xx_raises() -> None:
    with pytest.raises(ExternalServiceError):
        await _make(lambda req: httpx.Response(409)).release_payout(_request())


async def test_malformed_2xx_raises_and_no_amount_in_logs() -> None:
    client = _make(lambda req: httpx.Response(202, json={"wrong": "shape"}))
    with (
        mock.patch.object(adapter_module._logger, "warning") as warn,
        pytest.raises(ExternalServiceError),
    ):
        await client.release_payout(_request())
    logged = " ".join(str(c) for c in warn.mock_calls)
    assert "12345.67" not in logged  # сумма не в логах (ФЗ-152)
