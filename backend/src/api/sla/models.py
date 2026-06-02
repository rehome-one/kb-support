"""ORM-модели SLA — BusinessHours и SLAPolicy (ТЗ §3.8, FR-4.2; решения ADR-0007). E4-1 #85.

Конфигурационные справочники (нормативы SLA + рабочие часы) — **без ПДн**. Перечисления,
если появятся, хранятся как `String` + валидация Python-энумом на уровне приложения
(E1-конвенция, Issue #5, ADR-0007 — без нативного PG ENUM). Валидация формы JSONB-полей
(`schedule`, `applies_to`) — на границе API в CRUD (#86); на этом слое — сырой JSONB
(паттерн `Ticket.custom_fields`).

**Архитектурная константа (§3.10, ADR-0005).** FK только к СВОИМ таблицам: `SLAPolicy`
→ `business_hours` (своя), а заявка ссылается на политику через FK
`tickets.sla_policy_id → sla_policies.id` (добавляется миграцией #85 — выполняет обещание
из комментария модели `Ticket`). Никаких FK/SQL к чужим БД.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, TimestampMixin


class BusinessHours(TimestampMixin, Base):
    """График рабочего времени для расчёта SLA-дедлайнов (FR-4.2, ADR-0007 Решение 3).

    `schedule` — недельные интервалы рабочего времени (JSONB), напр.
    `{"mon": [["09:00", "18:00"]], "sat": [], ...}`. `timezone` — IANA-зона
    (напр. `"Europe/Moscow"`). Производственный календарь праздников РФ — отдельный
    follow-up (ADR-0007). Если у политики `business_hours_id IS NULL` — расчёт 24/7.
    Строгая валидация формы `schedule` — в CRUD (#86).
    """

    __tablename__ = "business_hours"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    def __repr__(self) -> str:
        return f"<BusinessHours id={self.id!r} name={self.name!r} tz={self.timezone!r}>"


class SLAPolicy(TimestampMixin, Base):
    """Политика SLA (ТЗ §3.8).

    `applies_to` (JSONB) — условия применения `{types, priorities, requester_roles}`
    (значения-строки доменов, НЕ FK к чужому). `priority` разрешает пересечение
    условий (выше — применяется раньше; матчинг — #87). Нормативы первого ответа и
    решения — в минутах. `business_hours_id IS NULL` → 24/7 (ADR-0007). Строгая
    валидация формы `applies_to` — в CRUD (#86).
    """

    __tablename__ = "sla_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    applies_to: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    first_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # FK на СВОЮ таблицу business_hours; ON DELETE SET NULL → удаление графика
    # деградирует политику к 24/7, не ломая её (ADR-0007).
    business_hours_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey(
            "business_hours.id",
            name="fk_sla_policies_business_hours_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    def __repr__(self) -> str:
        return f"<SLAPolicy id={self.id!r} name={self.name!r} priority={self.priority!r}>"
