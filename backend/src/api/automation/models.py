"""ORM-модель AutomationRule (ТЗ §3.9; решения ADR-0008). E5-1 #103.

Конфигурационный справочник правил автоматизации — **без ПДн**. Перечисление
`trigger` хранится как `String` + валидация Python-энумом на уровне приложения
(E1-конвенция, Issue #5, ADR-0007/0008 — без нативного PG ENUM). Форма JSONB-полей
(`conditions`, `actions`) на этом слое — **сырой JSONB** (паттерн
`SLAPolicy.applies_to`/`Ticket.custom_fields`); строгая типизация и валидация — на
границе API в CRUD (#104, ADR-0008 Решение 1).

**Архитектурная константа (§3.10, ADR-0005).** Таблица самостоятельна — **без FK**
(ни к чужим БД — арх-константа, ни к своим). Доступ к platform (пул операторов для
назначения и т.п.) — позже и только по HTTP, config-gated (#77).

**Поле `order` контракта ↔ колонка `apply_order`.** В контракте (`docs/openapi.yaml`)
поле называется `order`, но `order` — **зарезервированное слово SQL**. Колонка названа
`apply_order` (без кавычек/футгана), а внешнее имя `order` восстанавливается Pydantic-
алиасом в схеме CRUD (#104). Контрактного дрейфа нет — это решение реализации,
зафиксировано здесь, чтобы #104 не импровизировал.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Index, Integer, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, TimestampMixin


class AutomationRule(TimestampMixin, Base):
    """Правило автоматизации (ТЗ §3.9): trigger → conditions → actions.

    `trigger` — `AutomationTrigger` (валидация на границе #104). `conditions` (JSONB-
    object) — условия применения `{types, priorities, channels, keywords}` (отсутствует/
    пусто = wildcard, ADR-0008 Реш.1). `actions` (JSONB-array) — список действий
    `[{action, params}]`. `apply_order` — порядок применения (asc; конфликт = last-write-
    wins, ADR-0008 Реш.7); матчинг — #105. Форма conditions/actions валидируется в #104.
    """

    __tablename__ = "automation_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    actions: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Контрактное `order` (alias в #104); `apply_order` — обход зарезервированного SQL-слова.
    apply_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Индекс под запрос матчера (#105): активные правила данного триггера в порядке apply_order.
    __table_args__ = (
        Index(
            "ix_automation_rules_trigger_active_apply_order",
            "trigger",
            "is_active",
            "apply_order",
        ),
    )

    def __repr__(self) -> str:
        return f"<AutomationRule id={self.id!r} name={self.name!r} trigger={self.trigger!r}>"
