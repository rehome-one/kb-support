"""Тесты circuit breaker (E3-2). Clock инжектируется — без реального времени."""

from __future__ import annotations

import pytest

from api.clients.circuit_breaker import CircuitBreaker, CircuitState


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _breaker(clock: _Clock, *, threshold: int = 2, reset: float = 10.0) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=threshold, reset_timeout=reset, now=clock)


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0, reset_timeout=1.0, now=_Clock())


async def test_closed_allows() -> None:
    cb = _breaker(_Clock())
    assert await cb.acquire() is True
    assert cb.state == CircuitState.CLOSED


async def test_opens_after_threshold() -> None:
    cb = _breaker(_Clock(), threshold=2)
    for _ in range(2):
        assert await cb.acquire() is True
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN
    # OPEN отклоняет без вызова.
    assert await cb.acquire() is False


async def test_success_resets_failure_count() -> None:
    cb = _breaker(_Clock(), threshold=2)
    await cb.acquire()
    await cb.record_failure()
    await cb.acquire()
    await cb.record_success()  # сбрасывает счётчик
    await cb.acquire()
    await cb.record_failure()
    assert cb.state == CircuitState.CLOSED  # один сбой после сброса < порога


async def test_open_transitions_to_half_open_after_reset() -> None:
    clock = _Clock()
    cb = _breaker(clock, threshold=1, reset=10.0)
    await cb.acquire()
    await cb.record_failure()
    assert await cb.acquire() is False  # OPEN: до истечения reset вызов отклонён
    clock.t = 10.0
    assert await cb.acquire() is True  # проба разрешена
    assert cb.state == CircuitState.HALF_OPEN


async def test_half_open_allows_single_probe() -> None:
    clock = _Clock()
    cb = _breaker(clock, threshold=1, reset=5.0)
    await cb.acquire()
    await cb.record_failure()
    clock.t = 5.0
    assert await cb.acquire() is True  # первая проба
    assert await cb.acquire() is False  # вторая параллельная — отклонена


async def test_half_open_success_closes() -> None:
    clock = _Clock()
    cb = _breaker(clock, threshold=1, reset=5.0)
    await cb.acquire()
    await cb.record_failure()
    clock.t = 5.0
    await cb.acquire()
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert await cb.acquire() is True


async def test_half_open_failure_reopens() -> None:
    clock = _Clock()
    cb = _breaker(clock, threshold=1, reset=5.0)
    await cb.acquire()
    await cb.record_failure()
    clock.t = 5.0
    await cb.acquire()
    await cb.record_failure()  # проба провалилась
    assert cb.state == CircuitState.OPEN
    assert await cb.acquire() is False  # снова закрыт на reset (clock не двигали)
