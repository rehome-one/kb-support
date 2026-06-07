"""FastAPI-зависимость kb-files: per-request клиент загрузки вложений (E7-3, #145).

`get_kb_files_client` — per-request клиент или `None`, если интеграция выключена
(пустой `kb_files_api_token`). Паттерн повторяет `get_kb_wiki_client` (#129)/
`get_platform_client` (#71): config-gated, resilient AT-003 (#70). `StaticTokenProvider`
— ТОЛЬКО dev/test; реальный ClientCredentials — #77 (пустой токен fail-closed гейтит
загрузку). Фабрика живёт в `clients/` (не `email/`) — её зовут #145/#147/#149.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_files import HttpKbFilesClient, KbFilesClient
from api.clients.retry import RetryPolicy
from api.config import get_settings


async def get_kb_files_client() -> AsyncIterator[KbFilesClient | None]:
    """kb-files клиент или `None` (пустой `kb_files_api_token` → загрузка выключена)."""
    settings = get_settings()
    if not settings.kb_files_api_token:
        yield None
        return

    async with httpx.AsyncClient(
        base_url=settings.kb_files_api_base_url, timeout=settings.client_timeout_seconds
    ) as http:
        resilient = ResilientHttpClient(
            client_name="kb_files",
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
        yield HttpKbFilesClient(
            http_client=resilient,
            # TODO(#77): dev/test-only провайдер; боевой ClientCredentials — #77.
            token_provider=StaticTokenProvider(settings.kb_files_api_token),
        )
