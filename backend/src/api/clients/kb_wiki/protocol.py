"""Интерфейс клиента kb-wiki (E6-5, #129).

Потребитель (валидация linked_article_slug в #126/#129) зависит от Protocol, не от
HTTP-реализации/провизорной формы."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class KbWikiClient(Protocol):
    async def article_exists(self, slug: str) -> bool | None:
        """Существует ли статья с данным slug.

        `True` — статья есть (200); `False` — подтверждённо НЕТ (404) → валидация
        отклоняет; `None` — недоступность соседа/прочая ошибка (деградация AT-003) →
        валидация НЕ блокирует (slug принимается)."""
        ...
