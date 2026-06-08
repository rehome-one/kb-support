"""Фабрика per-request kb-search клиента (config-gated).

Естественный дом фабрики клиента kb-search (рядом с protocol/adapter/models).
Релоцирована сюда из `tickets/suggested_articles.py` при проводке analytics
containment-seam'а (#166) — оба потребителя (#130 suggested-articles и #166
аналитика) импортируют отсюда; дублировать фабрику того же клиента нельзя (правило
трёх). Частично закрывает #139 для kb_search.

Config-gate — пустой `kb_search_api_token` → `None` (интеграция выключена). Боевой
m2m-токен — #77 (сейчас `StaticTokenProvider`, dev/test).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_search.adapter import HttpKbSearchClient
from api.clients.kb_search.protocol import KbSearchClient
from api.clients.retry import RetryPolicy
from api.config import get_settings


async def get_kb_search_client() -> AsyncIterator[KbSearchClient | None]:
    """kb-search клиент или `None` (пустой `kb_search_api_token` → интеграция выключена)."""
    settings = get_settings()
    if not settings.kb_search_api_token:
        yield None
        return

    async with httpx.AsyncClient(
        base_url=settings.kb_search_api_base_url, timeout=settings.client_timeout_seconds
    ) as http:
        resilient = ResilientHttpClient(
            client_name="kb_search",
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
        yield HttpKbSearchClient(
            http_client=resilient,
            # TODO(#77): dev/test-only провайдер; боевой ClientCredentials — #77.
            token_provider=StaticTokenProvider(settings.kb_search_api_token),
        )
