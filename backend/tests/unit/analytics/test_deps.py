"""Unit-тест фабрики кэша аналитики (E8-2, #166): yield RedisCache + закрытие клиента."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import cast

from api.analytics.deps import get_analytics_cache
from api.clients.cache import Cache, RedisCache


def test_get_analytics_cache_yields_rediscache_and_closes() -> None:
    """Фабрика отдаёт RedisCache и закрывает клиент в finally (условие m1 ревью #166)."""

    async def _run() -> None:
        # Объявленный тип фабрики — AsyncIterator (без aclose); рантайм — async-генератор.
        gen = cast("AsyncGenerator[Cache, None]", get_analytics_cache())
        cache = await gen.__anext__()
        assert isinstance(cache, RedisCache)
        # Закрытие генератора триггерит finally (aclose клиента) — без утечки соединений.
        await gen.aclose()

    asyncio.run(_run())
