"""Unit-тесты actor'а time_based-воркера (#110) — без живой БД/broker.

`_scan_once` строит СВОЙ engine с NullPool (не модульный `api.db.engine`) и диспозит его;
коммитит проход (правила мутируют заявку). `check_time_based_rules` гоняет скан через
isolated loop; `enqueue_time_based_scan` инертен на StubBroker (config-gated).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from api.automation.worker import actor


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None


async def test_scan_once_uses_own_nullpool_engine_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    engine = _FakeEngine()

    def fake_create_engine(url: str, poolclass: object) -> _FakeEngine:
        captured["url"] = url
        captured["poolclass"] = poolclass
        return engine

    def fake_sessionmaker(bound: object, **_kw: object) -> Any:
        captured["bound"] = bound
        session = _FakeSession()
        captured["session"] = session
        return lambda: session

    async def fake_scan(session: object, **_kw: object) -> int:
        return 3

    monkeypatch.setattr(actor, "create_async_engine", fake_create_engine)
    monkeypatch.setattr(actor, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(actor, "scan_time_based", fake_scan)

    count = await actor._scan_once()

    assert count == 3
    assert captured["poolclass"] is NullPool  # свой engine, NullPool (урок #85)
    assert captured["bound"] is engine
    assert captured["session"].committed is True  # правила мутируют → проход закоммичен
    assert engine.disposed is True


async def test_scan_once_disposes_engine_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr(actor, "create_async_engine", lambda url, poolclass: engine)
    monkeypatch.setattr(actor, "async_sessionmaker", lambda bound, **kw: (lambda: _FakeSession()))

    async def boom(session: object, **_kw: object) -> int:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(actor, "scan_time_based", boom)

    with pytest.raises(RuntimeError):
        await actor._scan_once()
    assert engine.disposed is True  # finally диспозит даже при ошибке


async def test_scan_once_rolls_back_and_raises_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _FakeEngine()

    class _CommitFailSession(_FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.rolled_back = False

        async def commit(self) -> None:
            raise RuntimeError("commit boom")

        async def rollback(self) -> None:
            self.rolled_back = True

    session = _CommitFailSession()
    monkeypatch.setattr(actor, "create_async_engine", lambda url, poolclass: engine)
    monkeypatch.setattr(actor, "async_sessionmaker", lambda bound, **kw: (lambda: session))

    async def fake_scan(s: object, **_kw: object) -> int:
        return 1

    monkeypatch.setattr(actor, "scan_time_based", fake_scan)

    with pytest.raises(RuntimeError, match="commit boom"):
        await actor._scan_once()
    assert session.rolled_back is True  # сбой commit → откат прохода
    assert engine.disposed is True  # engine всё равно диспознут


def test_check_time_based_runs_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def fake_scan_once() -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(actor, "_scan_once", fake_scan_once)
    actor.check_time_based_rules()  # sync (Dramatiq), внутри asyncio.run
    assert calls == [1]


def test_enqueue_is_inert_on_stub_broker() -> None:
    # Дефолтный StubBroker: send не падает (боевой путь — после ops).
    actor.enqueue_time_based_scan()
