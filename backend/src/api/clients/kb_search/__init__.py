"""Клиент возврата ответа оператора в kb-search (E3-4, #72).

Публичная поверхность: `KbSearchClient` Protocol + `HttpKbSearchClient` +
`OperatorReply`/`ReplyOutcome`. Провизорный контракт (ADR-0006 Решение 3)
изолирован в `adapter.py`. Связь — только по HTTP (арх-константа)."""

from __future__ import annotations

from api.clients.kb_search.adapter import HttpKbSearchClient
from api.clients.kb_search.models import ArticleSuggestion, OperatorReply, ReplyOutcome
from api.clients.kb_search.protocol import KbSearchClient

__all__ = [
    "KbSearchClient",
    "HttpKbSearchClient",
    "ArticleSuggestion",
    "OperatorReply",
    "ReplyOutcome",
]
