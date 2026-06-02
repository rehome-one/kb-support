"""Сборка контекста заявителя для карточки оператора (enabler #81 для E3-5 #73). FR-2.2.

Оператору на карточке нужен профиль заявителя / квартира / бронь / коллаборант, чтобы
вести заявку (FR-2.2). Данные берутся из rehome.one platform ТОЛЬКО по HTTP через
`HttpPlatformClient` (#71) — архитектурная константа. Провизорный контракт платформы
изолирован в адаптере (ADR-0006); сюда приходят уже доменные DTO.

Graceful degradation (AT-003): platform-клиент (#71) НИКОГДА не бросает — недоступность
соседа / 404 / битый JSON он сам деградирует в `None` по секции. Поэтому сборка НЕ
оборачивается в try/except и `asyncio.gather` идёт без `return_exceptions`: глотать
нечего, а одна недоступная секция не должна ронять ни остальные, ни карточку.

Config-gating: пустой `platform_api_token` → интеграция выключена (`degraded=True`, все
секции `None`). `StaticTokenProvider` — ТОЛЬКО dev/test (см. `clients/auth.py`); реальный
ClientCredentials m2m-провайдер придёт с #77, до него боевой путь не активен (fail-closed).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.cache import InMemoryCache
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.platform import (
    Booking,
    Collaborator,
    HttpPlatformClient,
    PlatformClient,
    Premises,
    UserProfile,
)
from api.clients.retry import RetryPolicy
from api.config import get_settings
from api.tickets.models import Ticket


@dataclass(frozen=True)
class RequesterContext:
    """Собранный контекст заявителя. Любая секция `None` — сущности нет либо сосед
    недоступен (адаптер #71 не различает эти случаи).

    `degraded=True` означает, что интеграция с platform НЕ сконфигурирована (пустой
    токен, см. #77) — это про доступность ИНТЕГРАЦИИ, а не про существование конкретной
    сущности (отсутствующая сущность при включённой интеграции даёт секцию `None` при
    `degraded=False`)."""

    user: UserProfile | None
    premises: Premises | None
    booking: Booking | None
    collaborator: Collaborator | None
    degraded: bool


async def _absent() -> None:
    """Заглушка для отсутствующего id: `gather` ожидает awaitable по каждой секции."""
    return None


async def assemble_requester_context(
    ticket: Ticket, client: PlatformClient | None
) -> RequesterContext:
    """Собрать контекст заявителя из platform по идентификаторам заявки.

    `client is None` → интеграция выключена (gate): `degraded=True`, все секции `None`.
    Иначе — параллельные запросы ТОЛЬКО по непустым id; `requester_id` обязателен (NOT
    NULL), остальные секции опциональны. Адаптер (#71) сам деградирует в `None`, поэтому
    `gather` без `return_exceptions`.
    """
    if client is None:
        return RequesterContext(
            user=None, premises=None, booking=None, collaborator=None, degraded=True
        )

    user, premises, booking, collaborator = await asyncio.gather(
        client.get_user(ticket.requester_id),
        client.get_premises(ticket.premises_id) if ticket.premises_id else _absent(),
        client.get_booking(ticket.booking_id) if ticket.booking_id else _absent(),
        client.get_collaborator(ticket.collaborator_id) if ticket.collaborator_id else _absent(),
    )
    return RequesterContext(
        user=user,
        premises=premises,
        booking=booking,
        collaborator=collaborator,
        degraded=False,
    )


async def get_platform_client() -> AsyncIterator[PlatformClient | None]:
    """FastAPI-зависимость: per-request platform-клиент или `None`, если интеграция
    выключена (пустой `platform_api_token`).

    Per-request клиент повторяет паттерн #72 (`chat_return`). Кеш — `InMemoryCache` в
    рамках запроса: межзапросный Redis-кеш платформенных ПДн добавится с боевой проводкой
    (#77 / app-singleton клиент). Сейчас приоритет — не ронять карточку: адаптер #71
    читает `cache.get` вне своего try, поэтому `RedisCache` при недоступности Redis бросил
    бы исключение и дал 500, а `InMemoryCache` не бросает (AT-003).

    TODO(#77): заменить `StaticTokenProvider` на реальный ClientCredentials provider.
    Статичный токен — ТОЛЬКО dev/test (см. `clients/auth.py`); пустой токен гейтит
    интеграцию (fail-closed: без реального m2m боевой путь не активируется).
    """
    settings = get_settings()
    if not settings.platform_api_token:
        yield None
        return

    async with httpx.AsyncClient(
        base_url=settings.platform_api_base_url, timeout=settings.client_timeout_seconds
    ) as http:
        resilient = ResilientHttpClient(
            client_name="platform",
            http=http,
            breaker=CircuitBreaker(
                failure_threshold=settings.client_breaker_failure_threshold,
                reset_timeout=settings.client_breaker_reset_timeout,
                now=time.monotonic,
            ),
            retry=RetryPolicy(
                attempts=settings.client_retry_attempts,
                base_delay=settings.client_retry_base_delay,
                max_delay=settings.client_retry_max_delay,
            ),
        )
        yield HttpPlatformClient(
            http_client=resilient,
            # TODO(#77): dev/test-only провайдер; боевой ClientCredentials — #77.
            token_provider=StaticTokenProvider(settings.platform_api_token),
            cache=InMemoryCache(now=time.monotonic),
            cache_ttl_seconds=settings.platform_cache_ttl_seconds,
        )


__all__ = [
    "RequesterContext",
    "assemble_requester_context",
    "get_platform_client",
    "Booking",
    "Collaborator",
    "Premises",
    "UserProfile",
]
