"""Доменные DTO клиента kb-files (E7-1, #143).

Это НАШИ модели, независимые от провизорной формы kb-files API. Маппинг
провизорный JSON → этот DTO живёт в `adapter.py` (стиль ADR-0006/ADR-0010 Реш.4):
смена upstream-контракта правит только адаптер, не этот тип и не потребителя
(#145 ingestion / #148 веб-форма).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredFile:
    """Загруженное в kb-files вложение. `id` — строка: кладётся в
    `TicketMessage.attachments: list[str]` без uuid↔str на стыке."""

    id: str
    filename: str
    content_type: str
    size: int
