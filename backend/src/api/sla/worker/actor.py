"""Dramatiq-actor SLA-таймеров (E4-6, #90) — config-gated, инертен без broker.

Источник истины — БД (NFR-3.2): actor сканирует заявки по `*_due_at`, не держит
расписание в памяти → переживает перезапуск. Боевой путь — после ops (broker/
worker; пересекается с #79). Периодический запуск (periodiq/cron enqueue) — ops при
поднятии воркера; здесь только actor + enqueue-функция.
"""

from __future__ import annotations

import asyncio
import datetime

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.config import get_settings
from api.observability.logging import get_logger

# Импорт настраивает глобальный broker Dramatiq до объявления actor'а.
from api.sla.worker import broker as _broker  # noqa: F401
from api.sla.worker.hooks import on_sla_breach
from api.sla.worker.scan import scan_and_escalate

_logger = get_logger("sla.worker")


async def _scan_once() -> int:
    """Один проход скана со СВОИМ engine/NullPool.

    Свой engine (не модульный `api.db.engine`, привязанный к loop импорта) — иначе
    cross-loop asyncpg «Event loop is closed» (урок #85). E4 не пишет в БД (маркер
    дедупа — E5), поэтому commit не нужен. Engine диспозится в конце прохода.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            events = await scan_and_escalate(
                session,
                now=datetime.datetime.now(datetime.UTC),
                hook=on_sla_breach,
                batch_limit=settings.sla_scan_batch_limit,
            )
        return len(events)
    finally:
        await engine.dispose()


@dramatiq.actor(max_retries=3)
def check_sla_due() -> None:
    """Проактивная проверка дедлайнов SLA. Actor Dramatiq — sync; внутри isolated loop."""
    count = asyncio.run(_scan_once())
    _logger.info("sla_scan completed escalated=%s", count)


def enqueue_sla_scan() -> None:
    """Поставить задачу скана в очередь (ops-триггер / периодический запуск).

    Периодический вызов (periodiq/cron) подключает ops при поднятии воркера; без
    broker (StubBroker) `send` инертен.
    """
    check_sla_due.send()
