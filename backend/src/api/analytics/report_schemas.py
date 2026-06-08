"""Pydantic-схемы отчётов `GET /reports/{type}` (E8-3, #167).

Дискриминированный union по полю `report` (как #104). Каждый отчёт = `{report, period,
rows}`; типы строк различаются. nullable-агрегаты (`*_pct`/`avg_*`) — `float | None`
(инвариант нулевого знаменателя, ADR-0011 Реш.4; условие m3 ревью #167).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from api.analytics.reports import ReportData, ReportType
from api.analytics.schemas import PeriodInfo


class VolumeRow(BaseModel):
    dimension: str  # type | channel
    key: str
    count: int


class VolumeReport(BaseModel):
    report: Literal["volume"] = "volume"
    period: PeriodInfo
    rows: list[VolumeRow]


class SlaRow(BaseModel):
    first_response_compliance_pct: float | None
    resolution_compliance_pct: float | None
    breaches: int


class SlaReport(BaseModel):
    report: Literal["sla"] = "sla"
    period: PeriodInfo
    rows: list[SlaRow]


class SatisfactionRow(BaseModel):
    rating: int
    count: int


class SatisfactionReport(BaseModel):
    report: Literal["satisfaction"] = "satisfaction"
    period: PeriodInfo
    rows: list[SatisfactionRow]


class ReopensRow(BaseModel):
    total: int
    reopened: int
    reopened_rate_pct: float | None


class ReopensReport(BaseModel):
    report: Literal["reopens"] = "reopens"
    period: PeriodInfo
    rows: list[ReopensRow]


class OperatorsRow(BaseModel):
    operator_id: uuid.UUID
    resolved_count: int
    avg_resolution_minutes: float | None


class OperatorsReport(BaseModel):
    report: Literal["operators"] = "operators"
    period: PeriodInfo
    rows: list[OperatorsRow]


AnyReport = Annotated[
    VolumeReport | SlaReport | SatisfactionReport | ReopensReport | OperatorsReport,
    Field(discriminator="report"),
]


class ReportEnvelope(BaseModel):
    """Конверт ответа отчёта (как ResponseEnvelope: data + request_id)."""

    data: AnyReport
    request_id: uuid.UUID


def build_report_model(data: ReportData) -> AnyReport:
    """Построить типизированную модель отчёта из `ReportData` (валидирует строки)."""
    payload = {
        "period": PeriodInfo(from_=data.period.from_date, to=data.period.to_date),
        "rows": data.rows,
    }
    if data.report is ReportType.VOLUME:
        return VolumeReport.model_validate(payload)
    if data.report is ReportType.SLA:
        return SlaReport.model_validate(payload)
    if data.report is ReportType.SATISFACTION:
        return SatisfactionReport.model_validate(payload)
    if data.report is ReportType.REOPENS:
        return ReopensReport.model_validate(payload)
    return OperatorsReport.model_validate(payload)
