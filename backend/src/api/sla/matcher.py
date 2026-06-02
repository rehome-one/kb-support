"""Выбор SLA-политики для заявки (E4-3 #87, FR-4.1).

Чистая функция без I/O: на вход — уже загруженные активные политики (порядок
`priority desc, id` из `SLAPolicyRepository.list_active`), на выход — первая
подходящая или `None`. Загрузка из БД и проводка — в `assignment.py`.

**Матчинг** — конъюнкция измерений `applies_to`; отсутствующее/пустое измерение =
wildcard; пустой `applies_to={}` = catch-all. Сравнение по строковым значениям
доменных enum (в БД хранятся как `.value`).

**requester_roles (решение Архитектора #87, вариант A).** Роль заявителя на момент
создания заявки локально недоступна (она в platform UserProfile, интеграция
config-gated/#77). Поэтому политика с НЕпустым `requester_roles` НЕ матчится на
создании — условие по ролям нельзя подтвердить, role-специфичный SLA не применяем.
Role-матчинг включится позже, когда роль будет доступна (follow-up).
"""

from __future__ import annotations

from collections.abc import Sequence

from api.sla.models import SLAPolicy


def _dimension_ok(values: object, ticket_value: str) -> bool:
    """Измерение `applies_to` — wildcard (отсутствует/пусто) или содержит значение заявки."""
    if not isinstance(values, list) or not values:
        return True
    return ticket_value in values


def _policy_matches(applies_to: dict[str, object], ticket_type: str, ticket_priority: str) -> bool:
    """Подходит ли политика заявке данного типа/приоритета (вариант A для ролей)."""
    # Вариант A: НЕпустой requester_roles нельзя подтвердить локально → не матчим.
    roles = applies_to.get("requester_roles")
    if isinstance(roles, list) and roles:
        return False
    return _dimension_ok(applies_to.get("types"), ticket_type) and _dimension_ok(
        applies_to.get("priorities"), ticket_priority
    )


def select_policy(
    policies: Sequence[SLAPolicy], *, ticket_type: str, ticket_priority: str
) -> SLAPolicy | None:
    """Выбрать первую подходящую политику в порядке убывания приоритета.

    `policies` ожидаются отсортированными (`list_active`: priority desc, tie-break id)
    — выбор детерминирован. Нет подходящей → `None` (заявка без SLA).
    """
    for policy in policies:
        if _policy_matches(policy.applies_to, ticket_type, ticket_priority):
            return policy
    return None
