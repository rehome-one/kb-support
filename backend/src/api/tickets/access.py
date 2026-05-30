"""Storage-level фильтр видимости заявок (NFR-1.2, ADR-0003).

Фильтр применяется в SQL-запросе (не в Python), чтобы недоступные заявки не
покидали БД. Заявитель видит только свои (`requester_id`); оператор — заявки
своих команд (`team ∈ principal.teams`). Недоступная заявка неотличима от
несуществующей → вызывающий код отдаёт 404 (anti-enumeration).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_

from api.auth.principal import Principal
from api.tickets.models import Ticket


def visibility_filter(principal: Principal) -> ColumnElement[bool]:
    """SQL-условие видимости заявок для данного субъекта."""
    conditions: list[ColumnElement[bool]] = [Ticket.requester_id == principal.user_id]
    if principal.is_operator and principal.teams:
        conditions.append(Ticket.team.in_([team.value for team in principal.teams]))
    return or_(*conditions)
