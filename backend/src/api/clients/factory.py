"""Сборка `ResilientHttpClient` из настроек (E10-7 PR-2, #197).

Извлечено по правилу трёх (NIT ревью #213): одинаковый блок breaker+retry+метрики
повторялся в фабриках-зависимостях (`*/deps.py`) и в fire-after диспетчерах
(`payout_dispatch`/`decision_dispatch`). Здесь — единая сборка resilient-обёртки
поверх уже открытого `httpx.AsyncClient` (его жизненный цикл — у вызывающего:
per-request у Depends-фабрик, свой у fire-after-тасков).
"""

from __future__ import annotations

import time

import httpx

from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.retry import RetryPolicy
from api.config import Settings


def build_resilient_client(
    client_name: str, http: httpx.AsyncClient, settings: Settings
) -> ResilientHttpClient:
    """Обернуть открытый `httpx.AsyncClient` в `ResilientHttpClient` (timeout→breaker→retry)."""
    return ResilientHttpClient(
        client_name=client_name,
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
