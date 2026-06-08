"""Сборка отчётов FR-7.2 + CSV-экспорт (E8-3, #167).

Единая модель: **отчёт = упорядоченные колонки + строки** (`ReportData`). Один билдер на
тип отдаёт `ReportData`, из которой строится И типизированный JSON (`report_schemas`), И
CSV (`to_csv`) — один источник истины (условие m5 ревью #167).

Якоря периода — как ядро #165 (ADR-0011 Реш.4): volume/satisfaction/reopens когортно по
`created_at∈period`; **operators — resolved-anchor** (`resolved_at∈period`, решение Архитектора).
ФЗ-152: агрегаты без сырых ПДн (operators = uuid+счётчики; `rating_comment` НЕ выгружается).
"""

from __future__ import annotations

import csv
import enum
import io
from dataclasses import dataclass
from typing import Any

from api.analytics.period import StatsPeriod
from api.analytics.repository import AnalyticsRepository


class ReportType(str, enum.Enum):
    """Тип отчёта (домен из контракта `getReport`). Единственный источник домена."""

    VOLUME = "volume"
    SLA = "sla"
    SATISFACTION = "satisfaction"
    REOPENS = "reopens"
    OPERATORS = "operators"


class ReportFormat(str, enum.Enum):
    """Формат выгрузки отчёта (контракт `getReport.format`)."""

    JSON = "json"
    CSV = "csv"


@dataclass(frozen=True)
class ReportData:
    """Готовый отчёт: тип + период + стабильный порядок колонок + строки.

    `columns` фиксирует заголовок CSV даже при пустых `rows`. `rows` — плоские словари
    простых значений (int/float|None/str), пригодные и для JSON, и для CSV.
    """

    report: ReportType
    period: StatsPeriod
    columns: list[str]
    rows: list[dict[str, Any]]


async def _build_volume(repo: AnalyticsRepository, period: StatsPeriod) -> ReportData:
    counts = await repo.ticket_counts(period)
    # Long-format: dimension∈{type,channel}, key — значение домена, count — число заявок.
    rows: list[dict[str, Any]] = [
        {"dimension": "type", "key": key, "count": count}
        for key, count in sorted(counts.by_type.items())
    ]
    rows += [
        {"dimension": "channel", "key": key, "count": count}
        for key, count in sorted(counts.by_channel.items())
    ]
    return ReportData(ReportType.VOLUME, period, ["dimension", "key", "count"], rows)


async def _build_sla(repo: AnalyticsRepository, period: StatsPeriod, now: Any) -> ReportData:
    sla = await repo.sla_stats(period, now)
    rows = [
        {
            "first_response_compliance_pct": sla.first_response_compliance_pct,
            "resolution_compliance_pct": sla.resolution_compliance_pct,
            "breaches": sla.breaches,
        }
    ]
    columns = ["first_response_compliance_pct", "resolution_compliance_pct", "breaches"]
    return ReportData(ReportType.SLA, period, columns, rows)


async def _build_satisfaction(repo: AnalyticsRepository, period: StatsPeriod) -> ReportData:
    distribution = await repo.rating_distribution(period)
    # Полный диапазон 1..5 (нулевые включительно — условие m6 ревью #167), без «дыр».
    rows = [{"rating": rating, "count": distribution.get(rating, 0)} for rating in range(1, 6)]
    return ReportData(ReportType.SATISFACTION, period, ["rating", "count"], rows)


async def _build_reopens(repo: AnalyticsRepository, period: StatsPeriod) -> ReportData:
    total, reopened = await repo.reopen_stats(period)
    # Нулевой знаменатель → None (инвариант ADR-0011 Реш.4), как `_pct` ядра.
    rate = None if total == 0 else 100.0 * reopened / total
    rows = [{"total": total, "reopened": reopened, "reopened_rate_pct": rate}]
    return ReportData(ReportType.REOPENS, period, ["total", "reopened", "reopened_rate_pct"], rows)


async def _build_operators(repo: AnalyticsRepository, period: StatsPeriod) -> ReportData:
    stats = await repo.operator_stats(period)
    rows = [
        {
            "operator_id": str(s.operator_id),
            "resolved_count": s.resolved_count,
            "avg_resolution_minutes": s.avg_resolution_minutes,
        }
        for s in stats
    ]
    columns = ["operator_id", "resolved_count", "avg_resolution_minutes"]
    return ReportData(ReportType.OPERATORS, period, columns, rows)


async def build_report(
    repo: AnalyticsRepository, report_type: ReportType, period: StatsPeriod, *, now: Any
) -> ReportData:
    """Собрать отчёт по типу. `now` нужен только для SLA-breach (как ядро #165)."""
    if report_type is ReportType.VOLUME:
        return await _build_volume(repo, period)
    if report_type is ReportType.SLA:
        return await _build_sla(repo, period, now)
    if report_type is ReportType.SATISFACTION:
        return await _build_satisfaction(repo, period)
    if report_type is ReportType.REOPENS:
        return await _build_reopens(repo, period)
    return await _build_operators(repo, period)


def to_csv(report: ReportData) -> str:
    """Сериализовать отчёт в CSV (RFC4180, stdlib `csv`). None → пустая ячейка."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=report.columns, lineterminator="\n")
    writer.writeheader()
    for row in report.rows:
        writer.writerow({col: row.get(col) for col in report.columns})
    return buffer.getvalue()
