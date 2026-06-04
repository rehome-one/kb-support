"""SQL-предикаты нарушения SLA — единый источник для read-side фильтра и воркера.

Чтобы не плодить «третью семантику» breach (ADR-0007 Решение 1: один источник
правды), и `?sla_breached`-фильтр списка (`TicketRepository._list_conditions`), и
скан SLA-воркера (E4-6, #90) строят условие через эти функции. SQL-предикаты —
зеркало Python-проверок `is_resolution_breached` / `is_first_response_breached`
(`api.tickets.sla_state`):

- решение: `as_of = COALESCE(resolved_at, sla_paused_at, now)`; breach при
  `resolution_due_at IS NOT NULL AND as_of >= resolution_due_at` (пауза замораживает,
  late-resolve = breach);
- первый ответ: паузами НЕ двигается — breach при `first_response_due_at IS NOT NULL
  AND first_responded_at IS NULL AND now >= first_response_due_at`.
"""

from __future__ import annotations

import datetime

from sqlalchemy import ColumnElement, and_, func, or_

from api.tickets.models import Ticket


def resolution_breached_clause(now: datetime.datetime) -> ColumnElement[bool]:
    """Дедлайн РЕШЕНИЯ нарушен (зеркало `is_resolution_breached`)."""
    as_of = func.coalesce(Ticket.resolved_at, Ticket.sla_paused_at, now)
    return and_(Ticket.resolution_due_at.is_not(None), as_of >= Ticket.resolution_due_at)


def resolution_not_breached_clause(now: datetime.datetime) -> ColumnElement[bool]:
    """Логическое отрицание `resolution_breached_clause` (для `?sla_breached=false`)."""
    as_of = func.coalesce(Ticket.resolved_at, Ticket.sla_paused_at, now)
    return or_(Ticket.resolution_due_at.is_(None), as_of < Ticket.resolution_due_at)


def first_response_breached_clause(now: datetime.datetime) -> ColumnElement[bool]:
    """Дедлайн ПЕРВОГО ОТВЕТА нарушен (зеркало `is_first_response_breached`).

    Без COALESCE: первый ответ паузами не двигается; нога «открыта», пока нет
    `first_responded_at`.
    """
    return and_(
        Ticket.first_response_due_at.is_not(None),
        Ticket.first_responded_at.is_(None),
        Ticket.first_response_due_at <= now,
    )
