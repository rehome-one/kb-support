"""HTTP-клиент kb-wiki (E6-5, #129) — read-only проверка существования статьи по slug.

Поверх resilient-фундамента #70 (AT-003), провизорный контракт (ADR-0009 Решение 3,
стиль ADR-0006). Config-gated по пустому `kb_wiki_api_token` (инертно до #77). kb-support
НЕ создаёт/не редактирует контент БЗ (арх-константа, ADR-0005 Решение 1).
"""

from api.clients.kb_wiki.adapter import HttpKbWikiClient
from api.clients.kb_wiki.protocol import KbWikiClient

__all__ = ["HttpKbWikiClient", "KbWikiClient"]
