"""Unit-тесты JWKS-кеша (TTL + ротация по kid)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from api.auth.jwks import JwksCache, JwksUnknownKeyError
from tests.unit.auth.conftest import KID


@pytest.mark.asyncio
async def test_get_key_caches_within_ttl(jwks_dict: dict[str, Any]) -> None:
    calls = 0

    async def fetcher(url: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return jwks_dict

    cache = JwksCache("https://jwks", ttl_seconds=300, fetcher=fetcher)
    assert await cache.get_key(KID) is not None
    await cache.get_key(KID)
    assert calls == 1  # второй вызов в пределах TTL — без рефетча


@pytest.mark.asyncio
async def test_unknown_kid_refetches_then_raises(
    stub_fetcher: Callable[[str], Awaitable[dict[str, Any]]],
) -> None:
    cache = JwksCache("u", ttl_seconds=300, fetcher=stub_fetcher)
    with pytest.raises(JwksUnknownKeyError):
        await cache.get_key("does-not-exist")


@pytest.mark.asyncio
async def test_rotation_picks_up_new_kid(jwks_dict: dict[str, Any]) -> None:
    other = {**jwks_dict["keys"][0], "kid": "old-kid"}
    sequence = [{"keys": [other]}, jwks_dict]
    index = 0

    async def fetcher(url: str) -> dict[str, Any]:
        nonlocal index
        result = sequence[min(index, len(sequence) - 1)]
        index += 1
        return result

    cache = JwksCache("u", ttl_seconds=300, fetcher=fetcher)
    assert await cache.get_key("old-kid") is not None  # рефетч #1
    assert await cache.get_key(KID) is not None  # новый kid → рефетч #2 (ротация)
    assert index == 2
