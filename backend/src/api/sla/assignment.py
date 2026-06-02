"""Проводка SLA в создание заявки (E4-3 #87): матчинг политики + расчёт дедлайнов.

Единственное место с I/O и мутацией заявки (matcher/calculator — чистые). Вызывается
из `TicketRepository.create`/`create_from_chat` ПОСЛЕ `flush()` (нужен `ticket.created_at`
как якорь отсчёта) и ТОЛЬКО для вновь созданной заявки.

ADR-0007: дедлайны — источник истины БД, пишутся на создании (работают без воркера).
Нет подходящей политики → поля `sla_policy_id`/`*_due_at` остаются `None` (заявка без SLA).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.sla.calculator import compute_due_at
from api.sla.matcher import select_policy
from api.sla.repository import BusinessHoursRepository, SLAPolicyRepository
from api.tickets.models import Ticket


async def apply_sla(session: AsyncSession, ticket: Ticket) -> None:
    """Подобрать SLA-политику и проставить дедлайны на заявке (anchor — `created_at`).

    Вызывать ПОСЛЕ `flush()` (иначе `created_at` ещё `None`). Идемпотентно по смыслу:
    повторно на ту же заявку не вызывается (см. create_from_chat).
    """
    policies = await SLAPolicyRepository(session).list_active()
    policy = select_policy(policies, ticket_type=ticket.type, ticket_priority=ticket.priority)
    if policy is None:
        return

    business_hours = (
        await BusinessHoursRepository(session).get(policy.business_hours_id)
        if policy.business_hours_id is not None
        else None
    )
    ticket.sla_policy_id = policy.id
    ticket.first_response_due_at = compute_due_at(
        ticket.created_at, policy.first_response_minutes, business_hours
    )
    ticket.resolution_due_at = compute_due_at(
        ticket.created_at, policy.resolution_minutes, business_hours
    )
