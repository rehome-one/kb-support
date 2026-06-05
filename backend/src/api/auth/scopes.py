"""Именованные OAuth-скоупы kb-support (без магических строк в ветвлениях RBAC).

Скоуп считается бэкендом из проверенного JWT (CLAUDE.md: scope не из payload и не
с фронтенда). `staff_admin` — администрирование конфигурации службы поддержки
(SLA-политики, графики рабочего времени, справочники), §6 ТЗ.
"""

from __future__ import annotations

STAFF_ADMIN_SCOPE = "staff_admin"
"""Скоуп администратора: настройка SLA-политик / business hours и пр. конфигурации (§6)."""

STAFF_SUPPORT_SCOPE = "staff_support"
"""Скоуп поддержки: управление шаблонами ответов (CannedResponse CRUD, FR-5.1, ADR-0009).
Чтение/использование шаблонов (list/get/render) — любой оператор; CRUD — staff_support."""
