"""Предложение статей БЗ по содержанию заявки (E6-6 #130; FR-5.4, ADR-0009 Решение 3).

`suggest_for_ticket` строит запрос из subject+description заявки и зовёт kb-search;
деградация/выключено → пустой список + `degraded=True` (не 5xx). Только по HTTP, read-only
(арх-константа). Per-request фабрика клиента — `clients/kb_search/deps.get_kb_search_client`
(релоцирована туда в #166; config-gated по пустому `kb_search_api_token`).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from api.clients.kb_search import KbSearchClient
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
