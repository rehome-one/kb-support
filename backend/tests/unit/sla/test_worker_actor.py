"""Unit-тесты actor'а SLA-воркера (E4-6, #90) — без живой БД/broker.

Условие ревью #4: `_scan_once` строит СВОЙ engine с NullPool (не модульный
`api.db.engine`) и диспозит его. `check_sla_due` гоняет скан через isolated loop;
`enqueue_sla_scan` инертен на StubBroker.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from api.sla.worker import actor


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
        # С #108 actor коммитит проход (правила эскалации мутируют заявку).
        self.committed = True

    async def rollback(self) -> None:
        return None


async def test_scan_once_uses_own_nullpool_engine_and_disposes(
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

    async def fake_scan(session: object, **_kw: object) -> list[object]:
        return [object(), object()]

    monkeypatch.setattr(actor, "create_async_engine", fake_create_engine)
    monkeypatch.setattr(actor, "async_sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(actor, "scan_and_escalate", fake_scan)

    count = await actor._scan_once()

    assert count == 2
    assert captured["poolclass"] is NullPool  # свой engine, NullPool
    assert captured["bound"] is engine  # фабрика привязана к собственному engine
    assert captured["session"].committed is True  # #108: проход закоммичен
    assert engine.disposed is True  # engine диспознут в конце прохода


async def test_scan_once_disposes_engine_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr(actor, "create_async_engine", lambda url, poolclass: engine)
    monkeypatch.setattr(actor, "async_sessionmaker", lambda bound, **kw: (lambda: _FakeSession()))

    async def boom(session: object, **_kw: object) -> list[object]:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(actor, "scan_and_escalate", boom)

    with pytest.raises(RuntimeError):
        await actor._scan_once()
    assert engine.disposed is True  # finally диспозит даже при ошибке


def test_check_sla_due_runs_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def fake_scan_once() -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(actor, "_scan_once", fake_scan_once)
    # Actor вызывается синхронно (Dramatiq), внутри asyncio.run.
    actor.check_sla_due()
    assert calls == [1]


def test_enqueue_is_inert_on_stub_broker() -> None:
    # Дефолтный StubBroker: send не падает (боевой путь — после ops).
    actor.enqueue_sla_scan()
