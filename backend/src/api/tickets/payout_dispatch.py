"""Врезка платёжного пути претензий в переход case_state (E10-7 PR-1, #197, ADR-0014).

Два seam'а, оба config-gated (инертны до ops/#77):

- **releasePayout — fire-after best-effort** (U3, паттерн #72 chat_return): при переходе
  в PAID планируется фоновый запрос выплаты со СВОИМ httpx-клиентом; никогда не роняет
  процесс. `linked_payment_id` пишется НЕ здесь — через inbound webhook `payout_released`
  (E10-8) / durable доставку (#79). Деньги не считаем (FR-9.8) — передаём approved_amount.
- **PaymentReleaseChecker — синхронно при входе в PAYOUT_PENDING** (U4): информационный
  вердикт пишется в `TicketCaseDetails.payload["payment_clearance"]` в ТОЙ ЖЕ транзакции;
  case_state НЕ блокирует (NFR-4.4); деградация клиента (None) → флаг не пишется.
"""

from __future__ import annotations

import httpx
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.auth import StaticTokenProvider
from api.clients.bank import HttpBankProviderClient, PayoutRequest
from api.clients.factory import build_resilient_client
from api.clients.payment_checker import PaymentReleaseCheckerClient
from api.config import Settings
from api.observability.logging import get_logger
from api.tickets.case_repository import TicketCaseDetailsRepository
from api.tickets.enums import CaseType, TicketCaseState
from api.tickets.models import Ticket

_logger = get_logger("claims.payout")

_CURRENCY_RUB = "RUB"
_CLEARANCE_KEY = "payment_clearance"


def maybe_schedule_payout(
    background: BackgroundTasks,
    ticket: Ticket,
    old_case_state: str | None,
    settings: Settings,
) -> bool:
    """Запланировать fire-after выплату, если заявка ТОЛЬКО что перешла в PAID и банк включён.

    Извлекает плоский `PayoutRequest` синхронно (пока жива сессия). Возвращает факт
    планирования (для тестов). Без approved_amount — пропускаем (нечего выплачивать)."""
    if not settings.bank_provider_api_token:  # gate: банк выключен (инертно до #77)
        return False
    newly_paid = (
        ticket.case_state == TicketCaseState.PAID.value
        and old_case_state != TicketCaseState.PAID.value
    )
    if not newly_paid:
        return False
    if ticket.approved_amount is None:
        _logger.warning("payout skipped: no approved_amount ticket=%s", ticket.id)
        return False
    request = PayoutRequest(
        ticket_id=ticket.id,
        amount=ticket.approved_amount,
        currency=_CURRENCY_RUB,
        reference=ticket.number,
    )
    background.add_task(dispatch_payout, request, settings)
    return True


async def dispatch_payout(request: PayoutRequest, settings: Settings) -> None:
    """Фоновый запрос выплаты. Свой httpx-клиент (не request-сессия). Никогда не роняет
    процесс — best-effort (durable — #79). `linked_payment_id` — через webhook E10-8."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.bank_provider_api_base_url, timeout=settings.client_timeout_seconds
        ) as http:
            client = HttpBankProviderClient(
                http_client=build_resilient_client("bank", http, settings),
                token_provider=StaticTokenProvider(settings.bank_provider_api_token),
            )
            result = await client.release_payout(request)
        _logger.info(
            "payout requested ticket=%s payment_id=%s", request.ticket_id, result.payment_id
        )
    except Exception:  # последний рубеж: фоновый таск не должен ронять процесс
        _logger.warning("payout dispatch failed ticket=%s", request.ticket_id)


async def maybe_record_clearance(
    session: AsyncSession,
    ticket: Ticket,
    old_case_state: str | None,
    checker: PaymentReleaseCheckerClient | None,
) -> bool:
    """Синхронно (в request-транзакции) записать вердикт клиринга при входе в PAYOUT_PENDING.

    Информационно (U4): деградация клиента (None) → флаг не пишется, case_state не блокируется.
    Возвращает факт записи (для тестов). Вызывать ДО commit (флаг попадёт в ту же транзакцию)."""
    if checker is None:  # gate: проверка выключена (инертно до #77)
        return False
    newly_pending = (
        ticket.case_state == TicketCaseState.PAYOUT_PENDING.value
        and old_case_state != TicketCaseState.PAYOUT_PENDING.value
    )
    if not newly_pending:
        return False
    clearance = await checker.check_clearance(ticket.id)
    if clearance is None:  # деградация — флага нет, переход не блокируется
        return False
    repo = TicketCaseDetailsRepository(session)
    details = await repo.get_by_ticket(ticket.id)
    flag = {"clearable": clearance.clearable, "reason": clearance.reason}
    if details is None:
        await repo.create(ticket.id, CaseType(ticket.type), payload={_CLEARANCE_KEY: flag})
        return True
    payload = dict(details.payload or {})
    payload[_CLEARANCE_KEY] = flag
    await repo.update_payload(details, payload)
    return True
