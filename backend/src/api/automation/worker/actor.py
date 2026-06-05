"""Dramatiq-actor time_based-правил (E5, #110) — config-gated, инертен без broker.

Источник истины — БД (NFR-3.2): actor сканирует заявки по временным условиям правил
(`updated_at`/`created_at`/`first_responded_at`), не держит расписание в памяти →
переживает перезапуск. Боевой путь — после ops (broker/worker; пересекается с #79).
Периодический запуск (periodiq/cron enqueue) — ops при поднятии воркера; здесь только
actor + enqueue-функция.

Broker — ЕДИНЫЙ глобальный Dramatiq-broker сервиса (`api.sla.worker.broker`, config-gated
по `sla_worker_broker_url`): импортируется именно модуль `broker` (лёгкий — dramatiq+config,
без цикла импорта), НЕ `actor`. Пустой broker → StubBroker → actor инертен.
"""

from __future__ import annotations

import asyncio
import datetime

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.automation.time_based import scan_time_based
from api.config import get_settings
from api.observability.logging import get_logger

# Импорт настраивает глобальный broker Dramatiq до объявления actor'а (единый broker).
from api.sla.worker import broker as _broker  # noqa: F401

_logger = get_logger("automation.worker")


async def _scan_once() -> int:
    """Один проход скана time_based-правил со СВОИМ engine/NullPool.

    Свой engine (не модульный `api.db.engine`, привязанный к loop импорта) — иначе
    cross-loop asyncpg «Event loop is closed» (урок #85). Правила МУТИРУЮТ заявки
    (статус/приоритет/история) → проход коммитит; сбой commit'а логируется и
    откатывается. Engine диспозится в конце прохода. Без broker (StubBroker, config-gate
    по пустому `sla_worker_broker_url`) actor не enqueue'ится — путь инертен.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            count = await scan_time_based(
                session,
                now=datetime.datetime.now(datetime.UTC),
                batch_limit=settings.automation_scan_batch_limit,
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                _logger.error("time_based_scan commit failed — проход откачен", exc_info=True)
                raise
        return count
    finally:
        await engine.dispose()


@dramatiq.actor(max_retries=3)
def check_time_based_rules() -> None:
    """Проактивный прогон time_based-правил. Actor Dramatiq — sync; внутри isolated loop."""
    count = asyncio.run(_scan_once())
    _logger.info("time_based_scan completed fired=%s", count)


def enqueue_time_based_scan() -> None:
    """Поставить задачу скана в очередь (ops-триггер / периодический запуск).

    Периодический вызов (periodiq/cron) подключает ops при поднятии воркера; без broker
    (StubBroker) `send` инертен.
    """
    check_time_based_rules.send()
