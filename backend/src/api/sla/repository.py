"""Репозиторий чтения SLA-конфигурации (E4-1 #85).

Здесь — только чтение (нужно матчингу #87 и расчёту дедлайнов). CRUD-запись
(create/update) приходит с admin-эндпоинтами в #86.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.sla.models import BusinessHours, SLAPolicy


class SLAPolicyRepository:
    """Чтение SLA-политик поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> Sequence[SLAPolicy]:
        """Активные политики по убыванию `priority` (выше — раньше при матчинге #87).

        Tie-break по `id` — детерминированный порядок при равном priority."""
        stmt = (
            select(SLAPolicy)
            .where(SLAPolicy.is_active.is_(True))
            .order_by(SLAPolicy.priority.desc(), SLAPolicy.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, policy_id: uuid.UUID) -> SLAPolicy | None:
        return await self._session.get(SLAPolicy, policy_id)


class BusinessHoursRepository:
    """Чтение графиков рабочего времени поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, business_hours_id: uuid.UUID) -> BusinessHours | None:
        return await self._session.get(BusinessHours, business_hours_id)
