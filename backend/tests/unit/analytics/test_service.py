"""Unit-тесты AnalyticsService (E8-1, #165): cache-aside, деградация кэша, round-trip.

Репозиторий замокан (без БД); проверяем оркестрацию и кэш-поведение.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import cast

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
from api.analytics.service import AnalyticsService
from api.clients.cache import InMemoryCache

_PERIOD = StatsPeriod(from_date=datetime.date(2026, 1, 1), to_date=datetime.date(2026, 1, 31))
_NOW = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)

_COUNTS = TicketCounts(
    total=10,
    open=4,
    resolved=5,
    closed=3,
    by_type={"PAYMENT": 6, "OTHER": 4},
    by_channel={"AI_CHAT": 7, "EMAIL": 3},
)
_SLA = SlaStats(first_response_compliance_pct=80.0, resolution_compliance_pct=None, breaches=2)
_PERF = PerformanceStats(
    avg_first_response_minutes=12.5, avg_resolution_minutes=None, reopened_rate_pct=10.0
)
_QUALITY = QualityStats(avg_rating=4.5, ratings_count=4)


class _FakeRepository(AnalyticsRepository):
    """Репозиторий с заранее заданными агрегатами; считает обращения к ticket_counts."""

    def __init__(self) -> None:
        self.compute_calls = 0

    async def ticket_counts(self, period: StatsPeriod) -> TicketCounts:
        self.compute_calls += 1
        return _COUNTS

    async def sla_stats(self, period: StatsPeriod, now: datetime.datetime) -> SlaStats:
        return _SLA

    async def performance_stats(self, period: StatsPeriod) -> PerformanceStats:
        return _PERF

    async def quality_stats(self, period: StatsPeriod) -> QualityStats:
        return _QUALITY

    async def ai_chat_escalated(self, period: StatsPeriod) -> int:
        return 7


class _RaisingCache:
    """Кэш, всегда падающий на get/set — для проверки деградации (Cache Protocol #70)."""

    async def get(self, key: str) -> str | None:
        raise RuntimeError("cache down")

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise RuntimeError("cache down")


def _service(repo: AnalyticsRepository, cache: object) -> AnalyticsService:
    return AnalyticsService(repo, cast("InMemoryCache", cache), now=lambda: _NOW, ttl_seconds=60)


def test_assembles_full_stats_with_containment_none() -> None:
    repo = _FakeRepository()
    cache = InMemoryCache(now=lambda: 0.0)
    data = asyncio.run(_service(repo, cache).get_stats(_PERIOD))

    assert data.tickets == _COUNTS
    assert data.sla == _SLA
    assert data.performance == _PERF
    assert data.quality == _QUALITY
    assert data.ai_chat == AiChatStats(containment_rate_pct=None, escalated_count=7)
    assert data.period == _PERIOD


def test_cache_hit_skips_recompute_and_roundtrips_nested_dto() -> None:
    repo = _FakeRepository()
    cache = InMemoryCache(now=lambda: 0.0)  # часы не двигаются ⇒ TTL не истекает
    service = _service(repo, cache)

    first = asyncio.run(service.get_stats(_PERIOD))
    second = asyncio.run(service.get_stats(_PERIOD))

    assert repo.compute_calls == 1  # второй вызов обслужен из кэша
    # round-trip восстановил ИМЕННО вложенную структуру DTO (dict by_*, None-поля, floats).
    assert second == first
    assert isinstance(second, SupportStatsData)
    assert second.tickets.by_channel == {"AI_CHAT": 7, "EMAIL": 3}
    assert second.sla.resolution_compliance_pct is None
    assert second.period == _PERIOD


def test_cache_failure_degrades_to_direct_compute() -> None:
    repo = _FakeRepository()
    service = _service(repo, _RaisingCache())

    # Падающий кэш не должен ронять запрос — оба вызова считаются напрямую.
    first = asyncio.run(service.get_stats(_PERIOD))
    second = asyncio.run(service.get_stats(_PERIOD))

    assert repo.compute_calls == 2
    assert first == second
    assert first.ai_chat.escalated_count == 7
