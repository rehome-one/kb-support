"""Эндпоинты аналитики `GET /support/stats` (E8-2, #166) и `GET /support/reports/{type}`
(E8-3, #167).

Панель супервайзера (FR-7.1/7.3) и отчёты (FR-7.2). RBAC — `staff_supervisor` (ADR-0011
Решение 1): оператор без скоупа → 403. Период — UTC, дефолт 30 дней (ядро #165); `from > to`
→ 422. Containment AI-чата — config-gated kb-search seam (ADR-0011 Решение 3). Отчёты —
on-the-fly (без кэша, export-oriented), json (типизир. oneOf) или csv.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.analytics.containment import resolve_containment
from api.analytics.deps import get_analytics_cache
from api.analytics.period import PeriodError, StatsPeriod, resolve_period
from api.analytics.report_schemas import ReportEnvelope, build_report_model
from api.analytics.reports import ReportFormat, ReportType, build_report, to_csv
from api.analytics.repository import AnalyticsRepository
from api.analytics.schemas import SupportStats, SupportStatsEnvelope
from api.analytics.service import AnalyticsService
from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.clients.cache import Cache
from api.clients.kb_search import KbSearchClient
from api.clients.kb_search.deps import get_kb_search_client
from api.config import get_settings
from api.db import get_session
from api.errors import ProblemException

router = APIRouter(prefix="/api/v1/support", tags=["Analytics"])


def _resolve_request_id(raw: str | None) -> uuid.UUID:
    """Взять request_id из заголовка `X-Request-Id` или сгенерировать новый."""
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _require_supervisor(principal: Principal) -> None:
    """RBAC: вся аналитика — supervisor-only (ADR-0011 Решение 1, NFR-1.2), иначе 403."""
    if not principal.is_staff_supervisor:
        raise ProblemException.forbidden(detail="Staff supervisor scope required")


def _resolve_period_or_422(from_: datetime.date | None, to: datetime.date | None) -> StatsPeriod:
    try:
        return resolve_period(from_, to, today=_utcnow().date())
    except PeriodError as exc:
        raise ProblemException.unprocessable(detail="Invalid period: from must be <= to") from exc


@router.get(
    "/stats",
    response_model=SupportStatsEnvelope,
    summary="Сводные метрики поддержки",
)
async def get_support_stats(
    from_: datetime.date | None = Query(default=None, alias="from"),
    to: datetime.date | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    cache: Cache = Depends(get_analytics_cache),
    kb_search: KbSearchClient | None = Depends(get_kb_search_client),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> SupportStatsEnvelope:
    _require_supervisor(principal)
    period = _resolve_period_or_422(from_, to)

    settings = get_settings()
    service = AnalyticsService(
        AnalyticsRepository(session),
        cache,
        now=_utcnow,
        ttl_seconds=settings.analytics_cache_ttl_seconds,
    )
    data = await service.get_stats(period)
    containment_rate_pct, degraded = await resolve_containment(kb_search, period)

    stats = SupportStats.from_data(
        data, containment_rate_pct=containment_rate_pct, degraded=degraded
    )
    return SupportStatsEnvelope(data=stats, request_id=_resolve_request_id(x_request_id))


@router.get(
    "/reports/{report_type}",
    response_model=ReportEnvelope,
    summary="Отчёт поддержки",
)
async def get_report(
    report_type: ReportType,
    from_: datetime.date | None = Query(default=None, alias="from"),
    to: datetime.date | None = Query(default=None),
    report_format: ReportFormat = Query(default=ReportFormat.JSON, alias="format"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> ReportEnvelope | Response:
    # supervisor-only (как /stats). Неизвестный type/format → 422 (FastAPI enum-валидация).
    _require_supervisor(principal)
    period = _resolve_period_or_422(from_, to)

    # Отчёты — on-the-fly (export-oriented, без кэша; решение Архитектора A1, follow-up на кэш).
    data = await build_report(AnalyticsRepository(session), report_type, period, now=_utcnow())

    if report_format is ReportFormat.CSV:
        # Response (не response_model) — FastAPI пропускает как есть.
        return Response(content=to_csv(data), media_type="text/csv")

    return ReportEnvelope(
        data=build_report_model(data), request_id=_resolve_request_id(x_request_id)
    )
