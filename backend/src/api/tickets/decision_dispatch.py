"""Fire-after врезка решения претензии (E10-7 PR-2, #197, ADR-0014).

После `decide()` (FULL/PARTIAL/REJECTED) — два config-gated fire-after seam'а (паттерн
#72/#197, инертны до ops/#77), оба best-effort и НИКОГДА не роняют процесс:

- **FinancialLedger** — фиксация решения как проводки-ссылки (деньги не считаем, FR-9.8);
  gate по пустому `financial_ledger_api_token`.
- **Доставка решения в ЛК** заявителя (FR-9.3, ADR-0013 D7 seam) — outbound на платформу
  rehome.one (переиспользует `platform_api_*`, тот же сосед #71); gate по `platform_api_token`.

Вызывать ПОСЛЕ commit (decide() гарантирует свежесть: повтор решения → 409). Плоские DTO
извлекаются синхронно; фоновые таски строят СВОЙ httpx-клиент. Durable доставка — #79.
"""

from __future__ import annotations

import httpx
from fastapi import BackgroundTasks

from api.clients.auth import StaticTokenProvider
from api.clients.factory import build_resilient_client
from api.clients.financial_ledger import HttpFinancialLedgerClient, LedgerEntry
from api.clients.lk_notify import DecisionNotification, HttpLkNotifyClient
from api.config import Settings
from api.observability.logging import get_logger
from api.tickets.models import Ticket

_logger = get_logger("claims.decision")


def maybe_schedule_ledger(background: BackgroundTasks, ticket: Ticket, settings: Settings) -> bool:
    """Запланировать fire-after фиксацию решения в ledger, если интеграция включена."""
    if not settings.financial_ledger_api_token:  # gate (инертно до #77)
        return False
    if ticket.decision is None:  # без решения нечего фиксировать
        return False
    entry = LedgerEntry(
        ticket_id=ticket.id,
        decision=ticket.decision,
        amount=ticket.approved_amount,
        reference=ticket.number,
    )
    background.add_task(dispatch_ledger, entry, settings)
    return True


async def dispatch_ledger(entry: LedgerEntry, settings: Settings) -> None:
    """Фоновая запись проводки. Свой httpx-клиент. Никогда не роняет процесс (durable — #79)."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.financial_ledger_api_base_url,
            timeout=settings.client_timeout_seconds,
        ) as http:
            client = HttpFinancialLedgerClient(
                http_client=build_resilient_client("financial_ledger", http, settings),
                token_provider=StaticTokenProvider(settings.financial_ledger_api_token),
            )
            result = await client.record_entry(entry)
        _logger.info(
            "ledger entry recorded ticket=%s entry_id=%s", entry.ticket_id, result.entry_id
        )
    except Exception:  # последний рубеж: фоновый таск не должен ронять процесс
        _logger.warning("ledger record failed ticket=%s", entry.ticket_id)


def maybe_schedule_decision_delivery(
    background: BackgroundTasks, ticket: Ticket, settings: Settings
) -> bool:
    """Запланировать fire-after доставку решения в ЛК заявителя, если интеграция включена."""
    if not settings.platform_api_token:  # gate: тот же сосед #71 (инертно до #77)
        return False
    if ticket.decision is None:
        return False
    notification = DecisionNotification(
        ticket_id=ticket.id,
        requester_id=ticket.requester_id,
        decision=ticket.decision,
        approved_amount=ticket.approved_amount,
        reason=ticket.decision_reason,
    )
    background.add_task(dispatch_decision_delivery, notification, settings)
    return True


async def dispatch_decision_delivery(
    notification: DecisionNotification, settings: Settings
) -> None:
    """Фоновая доставка решения в ЛК. Свой httpx-клиент. Никогда не роняет процесс."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.platform_api_base_url, timeout=settings.client_timeout_seconds
        ) as http:
            client = HttpLkNotifyClient(
                http_client=build_resilient_client("lk_notify", http, settings),
                token_provider=StaticTokenProvider(settings.platform_api_token),
            )
            await client.notify_decision(notification)
        _logger.info("decision delivered to ЛК ticket=%s", notification.ticket_id)
    except Exception:  # последний рубеж
        _logger.warning("decision delivery failed ticket=%s", notification.ticket_id)
