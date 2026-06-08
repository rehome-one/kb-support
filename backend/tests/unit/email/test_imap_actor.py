"""Unit-тест инертности IMAP-actor (E7-4, #146) — без конфига и без БД.

Второй config-gate: пустой `imap_host` (дефолт) → проход no-op, БД не трогается.
"""

from __future__ import annotations

import asyncio

from api.email.worker.actor import _poll_once


def test_poll_inert_without_imap_host() -> None:
    # Дефолтный imap_host="" → actor не подключается к IMAP и не открывает engine.
    result = asyncio.run(_poll_once())
    assert result.fetched == 0
    assert result.ingested == 0
    assert result.skipped_oversized == 0
    assert result.failed == 0
