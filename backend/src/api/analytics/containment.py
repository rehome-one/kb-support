"""Containment-seam к kb-search для секции ai_chat (E8-2, #166; ADR-0011 Решение 3).

`resolve_containment` — config-gated: выключено (клиент `None`)/деградация (kb-search
вернул `None`) → `(None, degraded=True)`; иначе `(rate, False)`. Зеркало
`tickets/suggested_articles.suggest_for_ticket`. `escalated_count` считает ядро #165 само;
здесь — только containment (истинный знаменатель у kb-search).
"""

from __future__ import annotations

from api.analytics.period import StatsPeriod
from api.clients.kb_search import KbSearchClient


async def resolve_containment(
    kb_search: KbSearchClient | None, period: StatsPeriod
) -> tuple[float | None, bool]:
    """Containment rate + флаг деградации. Выключено/недоступно → `(None, True)`."""
    if kb_search is None:
        return None, True
    rate = await kb_search.get_containment_stats(period.from_date, period.to_date)
    if rate is None:
        return None, True
    return rate, False
