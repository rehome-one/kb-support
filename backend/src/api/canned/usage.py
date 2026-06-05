"""Учёт использования шаблонов (E6-4 #128; FR-5.1, ADR-0009 Решение 5).

`record_canned_usage` инкрементит `usage_count` при ответе из шаблона (`createMessage`
с `canned_response_id`). **Best-effort:** инкремент в SAVEPOINT — сбой (или несуществующий
шаблон) НЕ роняет отправку сообщения (статистика не критичнее ответа заявителю). Не
пробрасывает; пишет лог без ПДн (только id шаблона).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.canned.repository import CannedResponseRepository
from api.observability.logging import get_logger

_logger = get_logger("canned.usage")


async def record_canned_usage(session: AsyncSession, canned_response_id: uuid.UUID) -> None:
    """Best-effort инкремент usage_count шаблона в SAVEPOINT (не валит транзакцию сообщения).

    SAVEPOINT-изоляция: DB-сбой инкремента откатывается до savepoint, основная транзакция
    (сообщение + история) остаётся целой и пригодной к commit. Несуществующий шаблон →
    `increment_usage` вернёт False (0 строк) — лог, не ошибка."""
    try:
        savepoint = await session.begin_nested()
    except Exception:
        _logger.warning(
            "canned_usage_savepoint_begin_failed canned_response_id=%s",
            canned_response_id,
            exc_info=True,
        )
        return
    try:
        found = await CannedResponseRepository(session).increment_usage(canned_response_id)
        await savepoint.commit()
        if not found:
            _logger.info("canned_usage_skip_not_found canned_response_id=%s", canned_response_id)
    except Exception:
        _logger.warning(
            "canned_usage_increment_failed canned_response_id=%s",
            canned_response_id,
            exc_info=True,
        )
        try:
            await savepoint.rollback()
        except Exception:
            _logger.error(
                "canned_usage_savepoint_rollback_failed canned_response_id=%s",
                canned_response_id,
                exc_info=True,
            )
