"""Pydantic-схемы ответа `GET /support/stats` (E8-2, #166).

Зеркалят схему `SupportStats` контракта (`docs/openapi.yaml`). `*_pct`/`avg_*`/
`avg_rating`/`containment_rate_pct` — nullable (ядро #165 отдаёт `None` при нулевом
знаменателе, ADR-0011 Решение 4). `ai_chat.degraded` — флаг «containment недоступен»
(ADR-0011 Решение 3): containment тянется из kb-search config-gated seam.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, Field

from api.analytics.dto import SupportStatsData


class PeriodInfo(BaseModel):
    """Границы отчётного периода (даты UTC, включительно)."""

    # `from` — зарезервированное слово Python: поле `from_`, в JSON сериализуется как `from`
    # (serialization_alias; FastAPI отдаёт response_model by_alias).
    from_: datetime.date = Field(serialization_alias="from")
    to: datetime.date


class TicketCountsSchema(BaseModel):
    """Объёмы заявок: когортные total/resolved/closed/by_*, снапшот `open` (см. ядро #165)."""

    total: int
    open: int
    resolved: int
    closed: int
    by_type: dict[str, int]
    by_channel: dict[str, int]


class SlaSchema(BaseModel):
    first_response_compliance_pct: float | None
    resolution_compliance_pct: float | None
    breaches: int


class PerformanceSchema(BaseModel):
    avg_first_response_minutes: float | None
    avg_resolution_minutes: float | None
    reopened_rate_pct: float | None


class QualitySchema(BaseModel):
    avg_rating: float | None
    ratings_count: int


class AiChatSchema(BaseModel):
    """Метрики первой линии (kb-search). `degraded` — containment недоступен (seam off/сбой)."""

    containment_rate_pct: float | None
    escalated_count: int
    degraded: bool


class SupportStats(BaseModel):
    """Сводные метрики поддержки за период (FR-7.1/7.3)."""

    period: PeriodInfo
    tickets: TicketCountsSchema
    sla: SlaSchema
    performance: PerformanceSchema
    quality: QualitySchema
    ai_chat: AiChatSchema

    @classmethod
    def from_data(
        cls,
        data: SupportStatsData,
        *,
        containment_rate_pct: float | None,
        degraded: bool,
    ) -> SupportStats:
        """Собрать ответ из ядра #165 + результата containment-seam (#166)."""
        return cls(
            period=PeriodInfo(from_=data.period.from_date, to=data.period.to_date),
            tickets=TicketCountsSchema(
                total=data.tickets.total,
                open=data.tickets.open,
                resolved=data.tickets.resolved,
                closed=data.tickets.closed,
                by_type=data.tickets.by_type,
                by_channel=data.tickets.by_channel,
            ),
            sla=SlaSchema(
                first_response_compliance_pct=data.sla.first_response_compliance_pct,
                resolution_compliance_pct=data.sla.resolution_compliance_pct,
                breaches=data.sla.breaches,
            ),
            performance=PerformanceSchema(
                avg_first_response_minutes=data.performance.avg_first_response_minutes,
                avg_resolution_minutes=data.performance.avg_resolution_minutes,
                reopened_rate_pct=data.performance.reopened_rate_pct,
            ),
            quality=QualitySchema(
                avg_rating=data.quality.avg_rating,
                ratings_count=data.quality.ratings_count,
            ),
            # escalated_count — из ядра (своя БД); containment + degraded — из kb-search seam.
            ai_chat=AiChatSchema(
                containment_rate_pct=containment_rate_pct,
                escalated_count=data.ai_chat.escalated_count,
                degraded=degraded,
            ),
        )


class SupportStatsEnvelope(BaseModel):
    """Конверт ответа stats."""

    data: SupportStats
    request_id: uuid.UUID
