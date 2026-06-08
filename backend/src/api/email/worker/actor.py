"""Dramatiq-actor IMAP-приёма (E7-4, #146) — config-gated, инертен без конфига.

Двойной gate (как #90/#110 + второй слой): единый broker `api.sla.worker.broker`
(пустой `sla_worker_broker_url` → StubBroker → actor не enqueue'ится) И пустой
`imap_host` (проход — no-op, даже при поднятом broker). Источник истины — почтовый
ящик/БД (NFR-3.2): состояние не в памяти, повтор безопасен (дедуп по Message-ID, #145).

Свой NullPool-engine + `asyncio.run` + dispose (урок #85: модульный engine привязан к
loop импорта → cross-loop asyncpg). Периодический запуск (cron-enqueue) — ops при
поднятии воркера (без deps на планировщик). Боевой путь — после ops (broker/worker #79 +
IMAP-креды).
"""

from __future__ import annotations

import asyncio

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.config import get_settings
from api.email.worker.imap_client import ImaplibMailbox
from api.email.worker.poll import PollResult, poll_and_ingest
from api.observability.logging import get_logger

# Импорт настраивает единый глобальный broker Dramatiq до объявления actor'а.
from api.sla.worker import broker as _broker  # noqa: F401

_logger = get_logger("email.worker")


async def _poll_once() -> PollResult:
    """Один проход приёма со СВОИМ engine/NullPool. No-op без `imap_host`."""
    settings = get_settings()
    if not settings.imap_host:
        _logger.info("imap poll skipped: imap_host not configured")
        return PollResult(fetched=0, ingested=0, skipped_oversized=0, failed=0)

    mailbox = ImaplibMailbox.connect(settings)
    try:
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                # poll_and_ingest сам коммитит per-message (Д4) — общий tx тут не держим.
                return await poll_and_ingest(
                    session,
                    mailbox,
                    batch_limit=settings.imap_poll_batch_limit,
                    raw_max_bytes=settings.email_raw_max_bytes,
                    attachment_max_bytes=settings.email_attachment_max_bytes,
                    processed_mailbox=settings.imap_processed_mailbox,
                )
        finally:
            await engine.dispose()
    finally:
        try:
            mailbox.close()
        except Exception:
            _logger.warning("imap mailbox close failed")


@dramatiq.actor(max_retries=3)
def poll_inbox() -> None:
    """Проактивный приём входящих писем из IMAP-ящика. Sync actor; внутри isolated loop."""
    result = asyncio.run(_poll_once())
    _logger.info(
        "imap poll completed fetched=%d ingested=%d skipped=%d failed=%d",
        result.fetched,
        result.ingested,
        result.skipped_oversized,
        result.failed,
    )


def enqueue_poll_inbox() -> None:
    """Поставить задачу приёма в очередь (ops-триггер / периодический запуск).

    Периодический вызов (periodiq/cron) подключает ops при поднятии воркера; без broker
    (StubBroker) `send` инертен.
    """
    poll_inbox.send()
