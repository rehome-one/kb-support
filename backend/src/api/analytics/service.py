"""Сборка сводных метрик + cache-aside (E8-1, #165).

`AnalyticsService.get_stats(period)` собирает `SupportStatsData` из агрегатов
репозитория, кэшируя результат по периоду (ADR-0011 Решение 2: cache-aside с TTL,
`Cache` Protocol из #70 — InMemory в тестах, Redis в проде).

**Деградация кэша (условие ревью #165 / ADR-0011):** недоступность кэша (get/set)
НЕ валит запрос — логируем WARN и считаем напрямую. `now` инжектируется (момент для
breach-предиката + детерминизм тестов).

(Де)сериализация — явная (а не `dataclasses.asdict`): `SupportStatsData` вложенный
(period не date-JSON-сериализуем и в payload не пишется — он и так в ключе кэша),
round-trip восстанавливает именно вложенную структуру DTO.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable

from api.analytics.dto import (
    AiChatStats,
    PerformanceStats,
    QualityStats,
    SlaStats,
    SupportStatsData,
    TicketCounts,
)
from api.analytics.period import StatsPeriod
from api.analytics.repository import AnalyticsRepository
from api.clients.cache import Cache
from api.observability.logging import get_logger

_logger = get_logger("analytics.service")


class AnalyticsService:
    """Оркестрация агрегатов + cache-aside поверх `AnalyticsRepository`."""

    def __init__(
        self,
        repository: AnalyticsRepository,
        cache: Cache,
        *,
        now: Callable[[], datetime.datetime],
        ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._now = now
        self._ttl_seconds = ttl_seconds

    async def get_stats(self, period: StatsPeriod) -> SupportStatsData:
        key = _cache_key(period)
        cached = await self._cache_get(key)
        if cached is not None:
            return _deserialize(cached, period)
        data = await self._compute(period)
        await self._cache_set(key, _serialize(data))
        return data

    async def _compute(self, period: StatsPeriod) -> SupportStatsData:
        now = self._now()
        tickets = await self._repository.ticket_counts(period)
        sla = await self._repository.sla_stats(period, now)
        performance = await self._repository.performance_stats(period)
        quality = await self._repository.quality_stats(period)
        escalated = await self._repository.ai_chat_escalated(period)
        return SupportStatsData(
            period=period,
            tickets=tickets,
            sla=sla,
            performance=performance,
            quality=quality,
            # containment — config-gated seam к kb-search в #166; в ядре всегда None.
            ai_chat=AiChatStats(containment_rate_pct=None, escalated_count=escalated),
        )

    async def _cache_get(self, key: str) -> str | None:
        try:
            return await self._cache.get(key)
        except Exception:  # noqa: BLE001 — кэш не критичен: деградируем на прямой расчёт
            _logger.warning("analytics cache get failed; computing directly")
            return None

    async def _cache_set(self, key: str, value: str) -> None:
        try:
            await self._cache.set(key, value, self._ttl_seconds)
        except Exception:  # noqa: BLE001 — сбой записи в кэш не должен ронять запрос
            _logger.warning("analytics cache set failed; result not cached")


def _cache_key(period: StatsPeriod) -> str:
    # Ключ по УЖЕ разрешённым датам периода: дефолтный период (today-30..today) и явный
    # тот же диапазон делят один ключ; смена суток UTC естественно инвалидирует дефолт.
    return f"analytics:stats:{period.from_date.isoformat()}:{period.to_date.isoformat()}"


def _serialize(data: SupportStatsData) -> str:
    payload = {
        "tickets": {
            "total": data.tickets.total,
            "open": data.tickets.open,
            "resolved": data.tickets.resolved,
            "closed": data.tickets.closed,
            "by_type": data.tickets.by_type,
            "by_channel": data.tickets.by_channel,
        },
        "sla": {
            "first_response_compliance_pct": data.sla.first_response_compliance_pct,
            "resolution_compliance_pct": data.sla.resolution_compliance_pct,
            "breaches": data.sla.breaches,
        },
        "performance": {
            "avg_first_response_minutes": data.performance.avg_first_response_minutes,
            "avg_resolution_minutes": data.performance.avg_resolution_minutes,
            "reopened_rate_pct": data.performance.reopened_rate_pct,
        },
        "quality": {
            "avg_rating": data.quality.avg_rating,
            "ratings_count": data.quality.ratings_count,
        },
        "ai_chat": {
            "containment_rate_pct": data.ai_chat.containment_rate_pct,
            "escalated_count": data.ai_chat.escalated_count,
        },
    }
    return json.dumps(payload)


def _deserialize(raw: str, period: StatsPeriod) -> SupportStatsData:
    payload = json.loads(raw)
    return SupportStatsData(
        period=period,
        tickets=TicketCounts(**payload["tickets"]),
        sla=SlaStats(**payload["sla"]),
        performance=PerformanceStats(**payload["performance"]),
        quality=QualityStats(**payload["quality"]),
        ai_chat=AiChatStats(**payload["ai_chat"]),
    )
