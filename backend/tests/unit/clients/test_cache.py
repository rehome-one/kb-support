"""Тесты InMemoryCache (E3-2). TTL проверяется через инжектируемый clock."""

from __future__ import annotations

from api.clients.cache import Cache, InMemoryCache


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def test_miss_returns_none() -> None:
    cache = InMemoryCache(now=_Clock())
    assert await cache.get("nope") is None


async def test_set_then_hit() -> None:
    cache = InMemoryCache(now=_Clock())
    await cache.set("k", "v", ttl_seconds=60)
    assert await cache.get("k") == "v"


async def test_expiry_returns_none() -> None:
    clock = _Clock()
    cache = InMemoryCache(now=clock)
    await cache.set("k", "v", ttl_seconds=10)
    clock.t = 9.0
    assert await cache.get("k") == "v"
    clock.t = 10.0  # ровно TTL → истёк
    assert await cache.get("k") is None


def test_inmemory_satisfies_protocol() -> None:
    assert isinstance(InMemoryCache(now=_Clock()), Cache)
