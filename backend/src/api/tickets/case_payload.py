"""Валидатор payload `TicketCaseDetails` по case_type (E10-1 #191, §3.11, ADR-0013 D4).

Контракт: `TicketCaseDetails.payload` = `additionalProperties: true`; §3.11 даёт ПРИМЕРНЫЙ
(не закрытый) набор полей по типу. Поэтому политика — **allow-extra** (`extra="allow"`):
будущие поля (добираются в E10-5…E10-10) не ломают валидацию; при этом ИЗВЕСТНЫЕ поля §3.11
типизированы (если присутствуют — должны быть нужного типа). Service-слой, не БД.

`act_kind`/`signing_status` — typed top-level колонки `TicketCaseDetails` (по контракту), НЕ
в payload — здесь не дублируются.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from api.tickets.enums import CaseType


class _CasePayload(BaseModel):
    """База: разрешаем доп. поля (контракт additionalProperties:true), типизируем известные."""

    model_config = ConfigDict(extra="allow")


class CompensationPayload(_CasePayload):
    """COMPENSATION (§3.11/§3.3.1): лимит покрытия, зачёт обеспечительного, доказательства."""

    limit_remaining: float | None = None
    deposit_offset_amount: float | None = None
    evidence: list[str] | None = None
    independent_appraisal: bool | None = None
    late_submission: bool | None = None


class GuaranteePayload(_CasePayload):
    """GUARANTEE (§3.11/§3.3.2): регресс, плата за рассрочку, приостановка гарантии."""

    missed_payment_id: str | None = None
    guarantee_payout_id: str | None = None
    regress_due_at: str | None = None
    late_fee_accrued: float | None = None
    guarantee_paused: bool | None = None


class InsurancePayload(_CasePayload):
    """INSURANCE (§3.11/§3.3.3): страховое событие, статус у страховщика."""

    insurer_claim_ref: str | None = None
    insurer_status: str | None = None
    event_payload: dict[str, Any] | None = None


class AcceptanceActPayload(_CasePayload):
    """ACCEPTANCE_ACT (§3.11/§3.3.4): блокируемая выплата (act_kind/signing_status — typed-поля)."""

    blocked_payment_id: str | None = None


_VALIDATORS: dict[CaseType, type[_CasePayload]] = {
    CaseType.COMPENSATION: CompensationPayload,
    CaseType.GUARANTEE: GuaranteePayload,
    CaseType.INSURANCE: InsurancePayload,
    CaseType.ACCEPTANCE_ACT: AcceptanceActPayload,
}


def validate_case_payload(case_type: CaseType, payload: dict[str, Any]) -> dict[str, Any]:
    """Провалидировать payload по case_type → нормализованный dict (allow-extra сохраняется).

    Известные поля §3.11 типизируются (неверный тип → ValidationError); неизвестные поля
    пропускаются (контракт additionalProperties:true). `exclude_none` — не раздуваем хранимый
    JSONB null-ключами (известные-незаданные поля не пишем).
    """
    model = _VALIDATORS[case_type].model_validate(payload)
    return model.model_dump(mode="json", exclude_none=True)
