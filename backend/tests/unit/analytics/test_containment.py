"""Unit-тесты containment-seam (E8-2, #166): config-gate + деградация."""

from __future__ import annotations

import asyncio
import datetime

from api.analytics.containment import resolve_containment
from api.analytics.period import StatsPeriod

_PERIOD = StatsPeriod(from_date=datetime.date(2026, 5, 1), to_date=datetime.date(2026, 5, 31))


class _FakeKbSearch:
    def __init__(self, rate: float | None) -> None:
        self._rate = rate
        self.called_with: tuple[datetime.date, datetime.date] | None = None

    async def get_containment_stats(
        self, period_from: datetime.date, period_to: datetime.date
    ) -> float | None:
        self.called_with = (period_from, period_to)
        return self._rate


def test_disabled_client_is_degraded() -> None:
    rate, degraded = asyncio.run(resolve_containment(None, _PERIOD))
    assert rate is None
    assert degraded is True


def test_client_returns_rate_not_degraded() -> None:
    client = _FakeKbSearch(68.0)
    rate, degraded = asyncio.run(resolve_containment(client, _PERIOD))  # type: ignore[arg-type]
    assert rate == 68.0
    assert degraded is False
    assert client.called_with == (_PERIOD.from_date, _PERIOD.to_date)


def test_client_degradation_is_degraded() -> None:
    rate, degraded = asyncio.run(resolve_containment(_FakeKbSearch(None), _PERIOD))  # type: ignore[arg-type]
    assert rate is None
    assert degraded is True
