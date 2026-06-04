"""Unit-тесты config-gate брокера SLA-воркера (E4-6, #90).

Пустой `sla_worker_broker_url` → StubBroker (инертен); непустой → RedisBroker.
Без коннекта к Redis (RedisBroker не открывает соединение в конструкторе).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker

from api.sla.worker import broker as broker_mod


def _settings(url: str) -> SimpleNamespace:
    return SimpleNamespace(sla_worker_broker_url=url)


def test_empty_url_yields_stub_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(broker_mod, "get_settings", lambda: _settings(""))
    assert isinstance(broker_mod.build_broker(), StubBroker)


def test_nonempty_url_yields_redis_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(broker_mod, "get_settings", lambda: _settings("redis://localhost:6379/1"))
    built = broker_mod.build_broker()
    assert isinstance(built, RedisBroker)


def test_module_broker_is_stub_by_default() -> None:
    # При дефолтном (пустом) конфиге глобальный broker инертен.
    assert isinstance(broker_mod.broker, StubBroker)
