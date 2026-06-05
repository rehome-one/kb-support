"""Предложение статей БЗ по содержанию заявки (E6-6 #130; FR-5.4, ADR-0009 Решение 3).

`get_kb_search_client` — per-request kb-search клиент или `None` (config-gated по пустому
`kb_search_api_token`). `suggest_for_ticket` строит запрос из subject+description заявки и
зовёт kb-search; деградация/выключено → пустой список + `degraded=True` (не 5xx). Только по
HTTP, read-only (арх-константа). Кросс-запросный кеш — после app-singleton/#77 (как #81).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator

import httpx
from pydantic import BaseModel

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.kb_search import HttpKbSearchClient, KbSearchClient
from api.clients.retry import RetryPolicy
from api.config import get_settings
from api.tickets.models import Ticket


class SuggestedArticle(BaseModel):
    """Предложенная статья БЗ (без ПДн — публичный контент)."""

    slug: str
    title: str
    url: str | None = None


class SuggestedArticlesResult(BaseModel):
    """Результат: список статей + флаг деградации (интеграция выключена/недоступна)."""

    articles: list[SuggestedArticle]
    degraded: bool


class SuggestedArticlesEnvelope(BaseModel):
    """Конверт ответа suggested-articles."""

    data: SuggestedArticlesResult
    request_id: uuid.UUID


async def get_kb_search_client() -> AsyncIterator[KbSearchClient | None]:
    """kb-search клиент или `None` (пустой `kb_search_api_token` → предложения выключены)."""
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


async def suggest_for_ticket(
    ticket: Ticket, kb_search: KbSearchClient | None
) -> SuggestedArticlesResult:
    """Собрать предложения статей по заявке. Выключено/деградация → degraded=True, articles=[]."""
    if kb_search is None:
        return SuggestedArticlesResult(articles=[], degraded=True)
    query = f"{ticket.subject}\n{ticket.description}"
    result = await kb_search.suggest_articles(query)
    if result is None:
        return SuggestedArticlesResult(articles=[], degraded=True)
    return SuggestedArticlesResult(
        articles=[SuggestedArticle(slug=a.slug, title=a.title, url=a.url) for a in result],
        degraded=False,
    )
