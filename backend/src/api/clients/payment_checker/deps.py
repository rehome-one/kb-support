"""FastAPI-зависимость PaymentReleaseChecker: per-request клиент (E10-7, #197).

`get_payment_release_checker_client` — per-request клиент или `None`, если интеграция
выключена (пустой `payment_release_checker_api_token`). Паттерн повторяет
`get_kb_files_client` (#143): config-gated, resilient AT-003 (#70). `StaticTokenProvider`
— ТОЛЬКО dev/test; реальный ClientCredentials — #77.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.factory import build_resilient_client
from api.clients.payment_checker import HttpPaymentReleaseCheckerClient, PaymentReleaseCheckerClient
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
        yield HttpPaymentReleaseCheckerClient(
            http_client=build_resilient_client("payment_checker", http, settings),
            # TODO(#77): dev/test-only провайдер; боевой ClientCredentials — #77.
            token_provider=StaticTokenProvider(settings.payment_release_checker_api_token),
        )
