"""Fire-after передача события INSURANCE-заявки страховщику (E10-10 PR-B #200; ADR-0017 D3).

При **впервые входе INSURANCE-заявки в `UNDER_REVIEW`** (оператор передал материалы) —
config-gated fire-after передача в страховую (`clients/insurer`, паттерн #72/#197): свой httpx,
**never-raise** (мутация→raise клиента ловится здесь, не роняет переход). ФЗ-152: наружу только
`{ticket_id, insurance_event_id}`, логи — только id. Durable — #79.

Предикат `is_insurance_submitted` — единый источник (зеркало `is_newly_paid` в `payout_dispatch`,
рядом с потребителем; без копий).
"""

from __future__ import annotations

import httpx
from fastapi import BackgroundTasks

from api.clients.auth import StaticTokenProvider
from api.clients.factory import build_resilient_client
from api.clients.insurer import HttpInsurerClient, InsurerEvent
from api.config import Settings
from api.observability.logging import get_logger
from api.tickets.enums import TicketCaseState, TicketType
from api.tickets.models import Ticket

_logger = get_logger("claims.insurer")


def is_insurance_submitted(ticket: Ticket, old_case_state: str | None) -> bool:
    """INSURANCE-заявка ТОЛЬКО что вошла в UNDER_REVIEW (передача материалов страховщику)."""
    return (
        ticket.type == TicketType.INSURANCE.value
        and ticket.case_state == TicketCaseState.UNDER_REVIEW.value
        and old_case_state != TicketCaseState.UNDER_REVIEW.value
    )


def maybe_schedule_insurer_event(
    background: BackgroundTasks,
    ticket: Ticket,
    old_case_state: str | None,
    settings: Settings,
) -> bool:
    """Запланировать fire-after передачу события страховщику, если INSURANCE вошла в UNDER_REVIEW
    и интеграция включена. Возвращает факт планирования (для тестов)."""
    if not settings.insurer_api_token:  # gate: передача выключена (инертно до #77)
        return False
    if not is_insurance_submitted(ticket, old_case_state):
        return False
    event = InsurerEvent(ticket_id=ticket.id, insurance_event_id=ticket.insurance_event_id)
    background.add_task(dispatch_insurer_event, event, settings)
    return True


async def dispatch_insurer_event(event: InsurerEvent, settings: Settings) -> None:
    """Фоновая передача события страховщику. Свой httpx. Никогда не роняет процесс (#79)."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.insurer_api_base_url, timeout=settings.client_timeout_seconds
        ) as http:
            client = HttpInsurerClient(
                http_client=build_resilient_client("insurer", http, settings),
                token_provider=StaticTokenProvider(settings.insurer_api_token),
            )
            await client.send_event(event)
        _logger.info("insurer event sent ticket=%s", event.ticket_id)
    except Exception:  # последний рубеж: фоновый таск не должен ронять процесс
        _logger.warning("insurer event dispatch failed ticket=%s", event.ticket_id)
