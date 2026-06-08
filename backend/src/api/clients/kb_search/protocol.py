"""Интерфейс клиента возврата ответа в kb-search (E3-4, #72).

Триггер (chat-bridge) зависит от Protocol, не от HTTP-реализации. Метод никогда
не бросает на штатных исходах — отдаёт `ReplyOutcome` (деградация — не исключение).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.kb_search.models import (
    ArticleSuggestion,
    OperatorReply,
    ReplyOutcome,
    StatusNotification,
)


@runtime_checkable
class KbSearchClient(Protocol):
    async def send_operator_reply(self, reply: OperatorReply) -> ReplyOutcome: ...

    async def send_status_notification(self, notification: StatusNotification) -> ReplyOutcome:
        """Уведомить заявителя о смене статуса в chat-session (E7-8, #149).

        Выделенный путь (не operator-reply). Исходы как у reply: 202 → DELIVERED;
        404/409 → SESSION_GONE; сетевой сбой/circuit-open/прочее → DEGRADED."""
        ...

    async def suggest_articles(self, query: str) -> list[ArticleSuggestion] | None:
        """Предложить статьи БЗ по тексту запроса (FR-5.4, #130).

        `None` — недоступность kb-search/прочая ошибка (деградация AT-003) →
        вызывающий покажет «недоступно»; `[]` — поиск отработал, совпадений нет."""
        ...
