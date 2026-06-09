"""Тесты клиента доставки решения в ЛК (E10-7 PR-2, #197): notify_decision, raise, no-PII."""

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
from api.clients.lk_notify import DecisionNotification, HttpLkNotifyClient
from api.clients.lk_notify import adapter as adapter_module
from api.clients.retry import RetryPolicy

_TICKET = uuid.UUID("55555555-5555-5555-5555-555555555555")
_REQUESTER = uuid.UUID("66666666-6666-6666-6666-666666666666")


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 2
) -> HttpLkNotifyClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://platform")
    rc = ResilientHttpClient(
        client_name="lk_notify",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpLkNotifyClient(http_client=rc, token_provider=StaticTokenProvider("tok"))


def _notification() -> DecisionNotification:
    return DecisionNotification(
        ticket_id=_TICKET,
        requester_id=_REQUESTER,
        decision="PARTIAL",
        approved_amount=Decimal("500.00"),
        reason="секретная мотивировка",
    )


async def test_202_ok_no_raise() -> None:
    captured: dict[str, object] = {}

    def _h(req: httpx.Request) -> httpx.Response:
        captured["path"] = req.url.path
        captured["auth"] = req.headers.get("Authorization")
        return httpx.Response(202)

    await _make(_h).notify_decision(_notification())
    assert captured["path"] == f"/api/v1/claims/{_TICKET}/decision-notification"
    assert captured["auth"] == "Bearer tok"


async def test_5xx_propagates() -> None:
    with pytest.raises(ExternalServiceError):
        await _make(lambda req: httpx.Response(503), attempts=1).notify_decision(_notification())


async def test_4xx_raises() -> None:
    with pytest.raises(ExternalServiceError):
        await _make(lambda req: httpx.Response(400)).notify_decision(_notification())


async def test_4xx_no_reason_in_logs() -> None:
    with (
        mock.patch.object(adapter_module._logger, "warning") as warn,
        pytest.raises(ExternalServiceError),
    ):
        await _make(lambda req: httpx.Response(400)).notify_decision(_notification())
    logged = " ".join(str(c) for c in warn.mock_calls)
    assert "секретная" not in logged and "500.00" not in logged  # reason/сумма не в логах
