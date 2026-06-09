"""Приём претензионных заявок (E10-5 #195, FR-9.1, §3.4, ADR-0013 D10).

Claims создаются через generic `POST /tickets` (createTicket) с claims-`type` + `channel`
(LK_CLAIM/INSURER_WEBHOOK/SYSTEM). Контракт TicketCreate не несёт claim_amount/payload —
они приходят в `custom_fields` (решение Архитектора Q1). При приёме: инициализировать
`case_state=CLAIM_SUBMITTED`, извлечь claim_amount, собрать claims-payload (с флагами D10),
создать `TicketCaseDetails`. Маршрутизация тип/канал→команда — через AutomationRule on_create
(D8, Q3), здесь НЕ хардкодим. Деньги не считаем (FR-9.8) — суммы только храним.

Врезка — в `TicketRepository.create` ПОСЛЕ flush и ДО `_run_automation` (только для claims-типов).
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.tickets.case_repository import TicketCaseDetailsRepository
from api.tickets.claims_sla import compute_review_due_at
from api.tickets.enums import ActKind, CaseType, TicketCaseState
from api.tickets.models import Ticket

# Претензионные типы (= домен CaseType). Ровно для них инициализируется разбирательство.
CLAIMS_TYPES: frozenset[str] = frozenset(ct.value for ct in CaseType)

# COMPENSATION (§3.3.1 / Договор 5.8 / ADR-0013 D10).
INDEPENDENT_APPRAISAL_THRESHOLD = Decimal("50000")  # > этого → требование отчёта оценщика
LATE_SUBMISSION_WINDOW = datetime.timedelta(days=14)  # окно подачи (5.8.6)

# Ключи claims-данных в custom_fields (Q1).
_AMOUNT_KEY = "claim_amount"
_INCIDENT_KEY = "incident_date"
_EVIDENCE_KEY = "evidence"
_ACT_KIND_KEY = "act_kind"


def _parse_decimal(value: Any) -> Decimal | None:
    """Безопасно привести значение custom_fields к Decimal(0.01). Битое → None (не падаем)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_date(value: Any) -> datetime.date | None:
    """Безопасно привести ISO-строку custom_fields к date. Битое → None (не падаем)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _compensation_flags(custom_fields: dict[str, Any], *, now: datetime.date) -> dict[str, Any]:
    """Флаги приёма COMPENSATION (D10): >50k→independent_appraisal; вне 14 дн→late_submission."""
    flags: dict[str, Any] = {}
    amount = _parse_decimal(custom_fields.get(_AMOUNT_KEY))
    if amount is not None and amount > INDEPENDENT_APPRAISAL_THRESHOLD:
        flags["independent_appraisal"] = True
    incident = _parse_date(custom_fields.get(_INCIDENT_KEY))
    if incident is not None and (now - incident) > LATE_SUBMISSION_WINDOW:
        flags["late_submission"] = True  # вне окна — не отказ, флаг (D1); решает legal/finance
    evidence = custom_fields.get(_EVIDENCE_KEY)
    if isinstance(evidence, list):  # file_id в kb-files; мягко складываем, без жёсткого отказа
        flags["evidence"] = [str(f) for f in evidence]
    return flags


async def apply_claim_intake(
    session: AsyncSession, ticket: Ticket, *, now: datetime.date | None = None
) -> None:
    """Инициализировать разбирательство для claims-заявки (вызывать ТОЛЬКО при claims-типе).

    case_state=CLAIM_SUBMITTED; claim_amount из custom_fields; для COMPENSATION — флаги D10;
    создать TicketCaseDetails (payload валидируется по типу). Идемпотентно по созданию деталей
    (1:1, разовый вызов на create). Деньги не считаются — суммы только сохраняются.
    """
    today = now or datetime.datetime.now(datetime.UTC).date()
    case_type = CaseType(ticket.type)
    custom_fields = ticket.custom_fields or {}

    ticket.case_state = TicketCaseState.CLAIM_SUBMITTED.value
    ticket.claim_amount = _parse_decimal(custom_fields.get(_AMOUNT_KEY))
    # Срок рассмотрения 30 кал.дн (Договор 5.8.7, E10-6 #196, решение Архитектора Q3):
    # пишем в resolution_due_at — так дедлайн подключается к breach-машине E4 (read-side
    # #89 + worker #90). Переопределяет общий SLA-дедлайн (apply_sla отработал ДО intake).
    ticket.resolution_due_at = compute_review_due_at(ticket.created_at)

    payload: dict[str, Any] = {}
    if case_type is CaseType.COMPENSATION:
        payload = _compensation_flags(custom_fields, now=today)

    act_kind_raw = custom_fields.get(_ACT_KIND_KEY)
    act_kind = (
        ActKind(act_kind_raw)
        if case_type is CaseType.ACCEPTANCE_ACT and act_kind_raw in {a.value for a in ActKind}
        else None
    )

    await TicketCaseDetailsRepository(session).create(
        ticket.id, case_type, payload=payload, act_kind=act_kind
    )
