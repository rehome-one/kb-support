"""DI-зависимости эндпоинта аналитики (E8-2, #166).

`get_analytics_cache` — per-request `RedisCache` поверх `redis_url` (паттерн `check_redis`:
клиент закрывается в `finally`, иначе утечка соединений). Недоступность Redis НЕ валит
запрос — сервис #165 (`AnalyticsService._cache_get/_cache_set`) глотает ошибку с WARN и
считает напрямую (cache-aside деградация, не 5xx). Кросс-запросный кэш живёт в Redis-сервере;
app-singleton Redis-клиент — будущая оптимизация (как app-singleton заметки #81/#77).

Containment-клиент — общий `clients/kb_search/deps.get_kb_search_client` (config-gated).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from redis.asyncio import from_url

from api.clients.cache import Cache, RedisCache
from api.config import get_settings


async def get_analytics_cache() -> AsyncIterator[Cache]:
    """Per-request `RedisCache`. Недоступность Redis деградирует в сервисе (не 5xx)."""
    settings = get_settings()
    # redis-py from_url не типизирован под mypy strict (как в observability/health).
    client = from_url(settings.redis_url)  # type: ignore[no-untyped-call]
    try:
        yield RedisCache(client)
    finally:
        await client.aclose()
