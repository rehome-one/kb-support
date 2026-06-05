"""Интерфейс клиента возврата ответа в kb-search (E3-4, #72).

Триггер (chat-bridge) зависит от Protocol, не от HTTP-реализации. Метод никогда
не бросает на штатных исходах — отдаёт `ReplyOutcome` (деградация — не исключение).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.kb_search.models import ArticleSuggestion, OperatorReply, ReplyOutcome


@runtime_checkable
class KbSearchClient(Protocol):
    async def send_operator_reply(self, reply: OperatorReply) -> ReplyOutcome: ...

    async def suggest_articles(self, query: str) -> list[ArticleSuggestion] | None:
        """Предложить статьи БЗ по тексту запроса (FR-5.4, #130).

        `None` — недоступность kb-search/прочая ошибка (деградация AT-003) →
        вызывающий покажет «недоступно»; `[]` — поиск отработал, совпадений нет."""
        ...
