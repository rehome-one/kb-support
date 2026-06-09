"""FastAPI-зависимость PaymentReleaseChecker: per-request клиент (E10-7, #197).

`get_payment_release_checker_client` — per-request клиент или `None`, если интеграция
выключена (пустой `payment_release_checker_api_token`). Паттерн повторяет
`get_kb_files_client` (#143): config-gated, resilient AT-003 (#70). `StaticTokenProvider`
— ТОЛЬКО dev/test; реальный ClientCredentials — #77.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.payment_checker import HttpPaymentReleaseCheckerClient, PaymentReleaseCheckerClient
from api.clients.retry import RetryPolicy
from api.config import get_settings


async def get_payment_release_checker_client() -> AsyncIterator[PaymentReleaseCheckerClient | None]:
    """Checker-клиент или `None` (пустой токен → проверка выключена, ADR-0014 U4)."""
    settings = get_settings()
    if not settings.payment_release_checker_api_token:
        yield None
        return

    async with httpx.AsyncClient(
        base_url=settings.payment_release_checker_api_base_url,
        timeout=settings.client_timeout_seconds,
    ) as http:
        resilient = ResilientHttpClient(
            client_name="payment_checker",
            http=http,
            breaker=CircuitBreaker(
                failure_threshold=settings.client_breaker_failure_threshold,
                reset_timeout=settings.client_breaker_reset_timeout,
                now=time.monotonic,
            ),
            retry=RetryPolicy(
                attempts=settings.client_retry_attempts,
                base_delay=settings.client_retry_base_delay,
                max_delay=settings.client_retry_max_delay,
            ),
        )
        yield HttpPaymentReleaseCheckerClient(
            http_client=resilient,
            # TODO(#77): dev/test-only провайдер; боевой ClientCredentials — #77.
            token_provider=StaticTokenProvider(settings.payment_release_checker_api_token),
        )
