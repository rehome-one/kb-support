"""Config-gated Dramatiq broker SLA-воркера (E4-6, #90).

Пустой `sla_worker_broker_url` → `StubBroker` (actor регистрируется, но очередь
никто не потребляет — инертен). Непустой → `RedisBroker` (боевой путь, после ops).
Глобальный broker — требование дизайна Dramatiq (стек по ADR-0007/NFR-4.2), а не
ad-hoc singleton (CLAUDE.md «костыли»).
"""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.stub import StubBroker

from api.config import get_settings


def build_broker() -> dramatiq.Broker:
    """Собрать broker по конфигу: RedisBroker при заданном URL, иначе StubBroker."""
    url = get_settings().sla_worker_broker_url
    if url:
        # Ленивый импорт: не тянем redis-broker (и его коннект) в инертном режиме.
        from dramatiq.brokers.redis import RedisBroker

        return RedisBroker(url=url)
    return StubBroker()


broker: dramatiq.Broker = build_broker()
dramatiq.set_broker(broker)
