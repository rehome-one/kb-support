"""Тесты retry+backoff (E3-2). Детерминированы: sleep инжектируется (без реального сна)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from api.clients.retry import RetryPolicy, retry_async


class _Boom(Exception):
    pass


class _Other(Exception):
    pass


def test_backoff_is_exponential_capped() -> None:
    policy = RetryPolicy(attempts=5, base_delay=0.1, max_delay=0.5)
    assert policy.backoff(1) == pytest.approx(0.1)
    assert policy.backoff(2) == pytest.approx(0.2)
    assert policy.backoff(3) == pytest.approx(0.4)
    assert policy.backoff(4) == pytest.approx(0.5)  # capped at max_delay
    assert policy.backoff(5) == pytest.approx(0.5)


def test_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(attempts=0)


async def test_succeeds_first_try_no_sleep() -> None:
    delays: list[float] = []

    async def ok() -> str:
        return "ok"

    result = await retry_async(
        ok, RetryPolicy(attempts=3), retry_on=(_Boom,), sleep=_record(delays)
    )
    assert result == "ok"
    assert delays == []


async def test_succeeds_after_failures() -> None:
    delays: list[float] = []
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Boom
        return "ok"

    result = await retry_async(
        flaky, RetryPolicy(attempts=3, base_delay=0.1), retry_on=(_Boom,), sleep=_record(delays)
    )
    assert result == "ok"
    assert calls["n"] == 3
    assert delays == [pytest.approx(0.1), pytest.approx(0.2)]  # backoff before retries 2 и 3


async def test_exhausts_and_raises_last() -> None:
    calls = {"n": 0}

    async def always() -> str:
        calls["n"] += 1
        raise _Boom

    with pytest.raises(_Boom):
        await retry_async(always, RetryPolicy(attempts=3), retry_on=(_Boom,), sleep=_record([]))
    assert calls["n"] == 3


async def test_non_retryable_propagates_immediately() -> None:
    calls = {"n": 0}

    async def boom() -> str:
        calls["n"] += 1
        raise _Other

    with pytest.raises(_Other):
        await retry_async(boom, RetryPolicy(attempts=3), retry_on=(_Boom,), sleep=_record([]))
    assert calls["n"] == 1  # не ретраится


def _record(sink: list[float]) -> Callable[[float], Awaitable[None]]:
    async def _sleep(delay: float) -> None:
        sink.append(delay)

    return _sleep
