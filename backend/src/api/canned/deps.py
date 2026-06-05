"""FastAPI-зависимости шаблонов: per-request kb-wiki клиент (E6-5 #129).

`get_kb_wiki_client` — per-request клиент или `None`, если интеграция выключена (пустой
`kb_wiki_api_token`). Паттерн повторяет `get_platform_client` (#71): config-gated,
resilient AT-003 (#70). `StaticTokenProvider` — ТОЛЬКО dev/test; реальный
ClientCredentials — #77 (пустой токен fail-closed гейтит интеграцию).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_wiki import HttpKbWikiClient, KbWikiClient
from api.clients.retry import RetryPolicy
from api.config import get_settings


async def get_kb_wiki_client() -> AsyncIterator[KbWikiClient | None]:
    """kb-wiki клиент или `None` (пустой `kb_wiki_api_token` → валидация slug отключена)."""
    settings = get_settings()
    if not settings.kb_wiki_api_token:
        yield None
        return

    async with httpx.AsyncClient(
        base_url=settings.kb_wiki_api_base_url, timeout=settings.client_timeout_seconds
    ) as http:
        resilient = ResilientHttpClient(
            client_name="kb_wiki",
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
        yield HttpKbWikiClient(
            http_client=resilient,
            # TODO(#77): dev/test-only провайдер; боевой ClientCredentials — #77.
            token_provider=StaticTokenProvider(settings.kb_wiki_api_token),
        )
