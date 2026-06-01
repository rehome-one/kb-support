"""Слой HTTP-клиентов kb-support к соседям (rehome.one platform, kb-search).

Generic resilience-фундамент (E3-2, AT-003): timeout, retry+backoff, circuit
breaker, Redis-кеш, метрики. Конкретные клиенты (#71/#72) строятся поверх и
изолируют провизорный контракт ADR-0006 за adapter'ом.

Связь с соседями — ТОЛЬКО по HTTP (арх-константа): без shared-кода/SQL.
"""

from __future__ import annotations

from api.clients.base import ResilientHttpClient
from api.clients.cache import Cache, InMemoryCache, RedisCache
from api.clients.circuit_breaker import CircuitBreaker, CircuitState
from api.clients.errors import CircuitOpenError, ExternalServiceError
from api.clients.retry import RetryPolicy, retry_async

__all__ = [
    "ResilientHttpClient",
    "Cache",
    "InMemoryCache",
    "RedisCache",
    "CircuitBreaker",
    "CircuitState",
    "CircuitOpenError",
    "ExternalServiceError",
    "RetryPolicy",
    "retry_async",
]
