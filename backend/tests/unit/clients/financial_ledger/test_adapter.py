"""Тесты клиента FinancialLedger (E10-7 PR-2, #197): record_entry, raise-деградация, no-PII."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal
from unittest import mock

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.errors import ExternalServiceError
from api.clients.financial_ledger import HttpFinancialLedgerClient, LedgerEntry, LedgerResult
from api.clients.financial_ledger import adapter as adapter_module
from api.clients.retry import RetryPolicy

_TICKET = uuid.UUID("44444444-4444-4444-4444-444444444444")


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 2
) -> HttpFinancialLedgerClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ledger")
    rc = ResilientHttpClient(
        client_name="financial_ledger",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpFinancialLedgerClient(http_client=rc, token_provider=StaticTokenProvider("tok"))


def _entry(amount: Decimal | None = Decimal("999.99")) -> LedgerEntry:
    return LedgerEntry(ticket_id=_TICKET, decision="FULL", amount=amount, reference="RH-2026-00042")


async def test_202_returns_result() -> None:
    client = _make(lambda req: httpx.Response(202, json={"entry_id": "e-1"}))
    assert await client.record_entry(_entry()) == LedgerResult(entry_id="e-1")


async def test_amount_as_string_and_null_for_rejected() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(req.content)
        return httpx.Response(202, json={"entry_id": "e-2"})

    await _make(_h).record_entry(_entry(amount=None))
    assert captured["body"] == {
        "ticket_id": str(_TICKET),
        "decision": "FULL",
        "amount": None,  # REJECTED/без суммы → null
        "reference": "RH-2026-00042",
    }


async def test_nonzero_amount_serialized_as_string() -> None:
    # FR-9.8: точность — сумма строкой, НЕ float (ловит мутацию str→float).
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(req.content)
        return httpx.Response(202, json={"entry_id": "e-3"})

    await _make(_h).record_entry(_entry(amount=Decimal("999.99")))
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["amount"] == "999.99"  # строка, не 999.99 (float)


async def test_5xx_propagates() -> None:
    with pytest.raises(ExternalServiceError):
        await _make(lambda req: httpx.Response(503), attempts=1).record_entry(_entry())


async def test_4xx_raises() -> None:
    with pytest.raises(ExternalServiceError):
        await _make(lambda req: httpx.Response(422)).record_entry(_entry())


async def test_malformed_raises_and_no_amount_in_logs() -> None:
    client = _make(lambda req: httpx.Response(202, json={"nope": 1}))
    with (
        mock.patch.object(adapter_module._logger, "warning") as warn,
        pytest.raises(ExternalServiceError),
    ):
        await client.record_entry(_entry())
    assert "999.99" not in " ".join(str(c) for c in warn.mock_calls)
