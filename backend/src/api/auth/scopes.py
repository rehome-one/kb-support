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

STAFF_SUPERVISOR_SCOPE = "staff_supervisor"
"""Скоуп супервайзера: аналитика — панель и отчёты (FR-7.1/7.2, ADR-0011 Решение 1).

ТЗ §2.1 описывает Супервайзера как `staff_support + manage`; «manage» зафиксирован как
именованный scope `staff_supervisor` (а не магическая строка). **Аддитивно**: Keycloak
выдаёт супервайзеру ОБА скоупа (staff_support + staff_supervisor); код НЕ выводит один из
другого. `GET /support/stats` и `/support/reports/{type}` требуют этот скоуп; оператор → 403."""
