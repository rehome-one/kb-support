"""SLA-домен kb-support (E4): политики SLA, рабочие часы, расчёт дедлайнов.

E4-1 (#85) — ORM-модели `BusinessHours`/`SLAPolicy` + миграция. CRUD/OpenAPI — #86,
расчёт дедлайнов — #87, паузы — #88, breach — #89, Dramatiq-таймеры — #90. Решения —
ADR-0007. Связь — только своя БД (арх-константа)."""

from __future__ import annotations

from api.sla.models import BusinessHours, SLAPolicy

__all__ = ["BusinessHours", "SLAPolicy"]
