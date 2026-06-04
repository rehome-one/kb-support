"""Репозиторий правил автоматизации (E5-1 #103).

Чтение (`list_active`/`get`) нужно матчингу #105 и исполнению триггеров #107/#108/#110.
Запись (`list_all`/`create`/`update`) — admin-эндпоинтам #104. Commit — на стороне
вызывающего (паттерн `SLAPolicyRepository`/`TicketRepository`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.automation.models import AutomationRule


class AutomationRuleRepository:
    """Чтение и запись правил автоматизации поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, trigger: str | None = None) -> Sequence[AutomationRule]:
        """Активные правила в порядке `apply_order` asc (тай-брейк `id` — детерминизм #105).

        `trigger=None` → ВСЕ активные правила; `trigger=<value>` → только данного триггера
        (фильтр на стороне БД для матчинга конкретного события)."""
        stmt = select(AutomationRule).where(AutomationRule.is_active.is_(True))
        if trigger is not None:
            stmt = stmt.where(AutomationRule.trigger == trigger)
        stmt = stmt.order_by(AutomationRule.apply_order.asc(), AutomationRule.id)
        return (await self._session.execute(stmt)).scalars().all()

    async def list_all(self) -> Sequence[AutomationRule]:
        """Все правила (вкл. неактивные) — для admin-списка (#104). Порядок как `list_active`."""
        stmt = select(AutomationRule).order_by(AutomationRule.apply_order.asc(), AutomationRule.id)
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, rule_id: uuid.UUID) -> AutomationRule | None:
        return await self._session.get(AutomationRule, rule_id)

    async def create(self, values: dict[str, Any]) -> AutomationRule:
        """Создать правило из готовых значений колонок (валидация — в схеме/роутере #104)."""
        rule = AutomationRule(**values)
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def update(self, rule: AutomationRule, changes: dict[str, Any]) -> AutomationRule:
        """Применить частичное обновление (только переданные колонки) + flush."""
        for column, value in changes.items():
            setattr(rule, column, value)
        await self._session.flush()
        return rule
