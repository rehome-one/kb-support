"""Эндпоинт аналитики `GET /support/stats` (E8-2, #166).

Панель супервайзера (FR-7.1/7.3). RBAC — `staff_supervisor` (ADR-0011 Решение 1):
оператор без скоупа → 403. Период — UTC, дефолт 30 дней (ядро #165); `from > to` → 422.
Containment AI-чата — config-gated kb-search seam (ADR-0011 Решение 3): выключено/недоступно
→ `degraded=true`, `containment_rate_pct=null`. Тяжёлая SQL-агрегация кэшируется (#165);
containment — живой seam-вызов на запрос (escalated_count берётся из кэшированного ядра).
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.analytics.containment import resolve_containment
from api.analytics.deps import get_analytics_cache
from api.analytics.period import PeriodError, resolve_period
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
    # Вся аналитика — supervisor-only (ADR-0011 Решение 1, NFR-1.2). Оператор без скоупа → 403.
    if not principal.is_staff_supervisor:
        raise ProblemException.forbidden(detail="Staff supervisor scope required")

    try:
        period = resolve_period(from_, to, today=_utcnow().date())
    except PeriodError as exc:
        raise ProblemException.unprocessable(detail="Invalid period: from must be <= to") from exc

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
