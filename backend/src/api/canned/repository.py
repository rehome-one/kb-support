"""Репозиторий шаблонов ответов (E6-1 #125).

Чтение (`list`/`get`) — listCannedResponses/render (#126/#127); запись (`create`/
`update`) — admin CRUD (#126); `increment_usage` — учёт при ответе из шаблона (#128).
Commit — на стороне вызывающего (паттерн `SLAPolicyRepository`): роутер коммитит после
успешной мутации.

Без cursor-пагинации (как SLA/automation в E4/E5): шаблоны — bounded curated-набор,
список целиком; уточнение контракта `listCannedResponses` — #126.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.canned.models import CannedResponse


class CannedResponseRepository:
    """Чтение и запись шаблонов ответов поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, *, type_filter: str | None = None) -> Sequence[CannedResponse]:
        """Шаблоны, опц. фильтр по `type`. Детерминированный порядок (`created_at desc, id`)."""
        stmt = select(CannedResponse)
        if type_filter is not None:
            stmt = stmt.where(CannedResponse.type == type_filter)
        stmt = stmt.order_by(CannedResponse.created_at.desc(), CannedResponse.id)
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, canned_id: uuid.UUID) -> CannedResponse | None:
        return await self._session.get(CannedResponse, canned_id)

    async def create(self, values: dict[str, Any]) -> CannedResponse:
        """Создать шаблон из готовых значений колонок (валидация — в схеме/роутере #126)."""
        canned = CannedResponse(**values)
        self._session.add(canned)
        await self._session.flush()
        return canned

    async def update(self, canned: CannedResponse, changes: dict[str, Any]) -> CannedResponse:
        """Применить частичное обновление (только переданные колонки) + flush."""
        for column, value in changes.items():
            setattr(canned, column, value)
        await self._session.flush()
        return canned

    async def increment_usage(self, canned_id: uuid.UUID) -> bool:
        """Атомарно увеличить usage_count на 1 (для учёта при ответе из шаблона #128).

        Атомарный `UPDATE ... SET usage_count = usage_count + 1` (без read-modify-write —
        нет гонки). Возвращает True, если строка найдена/обновлена, иначе False (шаблон
        мог быть удалён — best-effort у вызывающего #128)."""
        stmt = (
            update(CannedResponse)
            .where(CannedResponse.id == canned_id)
            .values(usage_count=CannedResponse.usage_count + 1)
        )
        # execute(UPDATE) возвращает CursorResult (rowcount), но статически типизирован
        # как Result — узкий каст для доступа к rowcount (DML, не SELECT).
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return result.rowcount > 0
