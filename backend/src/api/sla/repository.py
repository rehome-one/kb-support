"""Репозиторий SLA-конфигурации (E4-1 #85, расширен admin CRUD в E4-2 #86).

Чтение (`list_active`/`get`) нужно матчингу #87. Запись (`list_all`/`create`/
`update`) — admin-эндпоинтам #86. Commit — на стороне вызывающего (паттерн
`TicketRepository`): роутер коммитит после успешной мутации.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.sla.models import BusinessHours, SLAPolicy


class SLAPolicyRepository:
    """Чтение и запись SLA-политик поверх `AsyncSession`."""

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

    async def list_all(self) -> Sequence[SLAPolicy]:
        """Все политики (вкл. неактивные) — для admin-списка. Порядок как `list_active`."""
        stmt = select(SLAPolicy).order_by(SLAPolicy.priority.desc(), SLAPolicy.id)
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, policy_id: uuid.UUID) -> SLAPolicy | None:
        return await self._session.get(SLAPolicy, policy_id)

    async def create(self, values: dict[str, Any]) -> SLAPolicy:
        """Создать политику из готовых значений колонок (валидация — в схеме/роутере)."""
        policy = SLAPolicy(**values)
        self._session.add(policy)
        await self._session.flush()
        return policy

    async def update(self, policy: SLAPolicy, changes: dict[str, Any]) -> SLAPolicy:
        """Применить частичное обновление (только переданные колонки) + flush."""
        for column, value in changes.items():
            setattr(policy, column, value)
        await self._session.flush()
        return policy


class BusinessHoursRepository:
    """Чтение и запись графиков рабочего времени поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, business_hours_id: uuid.UUID) -> BusinessHours | None:
        return await self._session.get(BusinessHours, business_hours_id)

    async def list_all(self) -> Sequence[BusinessHours]:
        """Все графики (вкл. неактивные) — для admin-списка. Порядок по `name`, `id`."""
        stmt = select(BusinessHours).order_by(BusinessHours.name, BusinessHours.id)
        return (await self._session.execute(stmt)).scalars().all()

    async def create(self, values: dict[str, Any]) -> BusinessHours:
        """Создать график из готовых значений колонок."""
        business_hours = BusinessHours(**values)
        self._session.add(business_hours)
        await self._session.flush()
        return business_hours

    async def update(self, business_hours: BusinessHours, changes: dict[str, Any]) -> BusinessHours:
        """Применить частичное обновление (только переданные колонки) + flush."""
        for column, value in changes.items():
            setattr(business_hours, column, value)
        await self._session.flush()
        return business_hours
