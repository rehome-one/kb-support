"""Unit-тесты сборки отчётов + CSV (E8-3, #167). Репозиторий замокан (без БД)."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import cast

from api.analytics.dto import OperatorStat, SlaStats, TicketCounts
from api.analytics.period import StatsPeriod
from api.analytics.report_schemas import build_report_model
from api.analytics.reports import ReportData, ReportType, build_report, to_csv
from api.analytics.repository import AnalyticsRepository

_PERIOD = StatsPeriod(from_date=datetime.date(2026, 1, 1), to_date=datetime.date(2026, 1, 31))
_NOW = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
_OP1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OP2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeRepository:
    """Standalone fake (не subclass — иначе mypy резолвит базу как Any в этом модуле)."""

    async def ticket_counts(self, period: StatsPeriod) -> TicketCounts:
        return TicketCounts(
            total=5,
            open=2,
            resolved=2,
            closed=1,
            by_type={"PAYMENT": 3, "OTHER": 2},
            by_channel={"AI_CHAT": 4, "EMAIL": 1},
        )

    async def sla_stats(self, period: StatsPeriod, now: datetime.datetime) -> SlaStats:
        return SlaStats(
            first_response_compliance_pct=80.0, resolution_compliance_pct=None, breaches=1
        )

    async def rating_distribution(self, period: StatsPeriod) -> dict[int, int]:
        return {5: 3, 3: 1}

    async def reopen_stats(self, period: StatsPeriod) -> tuple[int, int]:
        return 5, 2

    async def operator_stats(self, period: StatsPeriod) -> list[OperatorStat]:
        return [
            OperatorStat(operator_id=_OP1, resolved_count=4, avg_resolution_minutes=30.0),
            OperatorStat(operator_id=_OP2, resolved_count=1, avg_resolution_minutes=None),
        ]


def _build(report_type: ReportType) -> ReportData:
    repo = cast("AnalyticsRepository", _FakeRepository())
    return asyncio.run(build_report(repo, report_type, _PERIOD, now=_NOW))


def test_volume_long_format_sorted() -> None:
    data = _build(ReportType.VOLUME)
    assert data.columns == ["dimension", "key", "count"]
    assert data.rows == [
        {"dimension": "type", "key": "OTHER", "count": 2},
        {"dimension": "type", "key": "PAYMENT", "count": 3},
        {"dimension": "channel", "key": "AI_CHAT", "count": 4},
        {"dimension": "channel", "key": "EMAIL", "count": 1},
    ]


def test_sla_single_row_nullable() -> None:
    data = _build(ReportType.SLA)
    assert data.rows == [
        {
            "first_response_compliance_pct": 80.0,
            "resolution_compliance_pct": None,
            "breaches": 1,
        }
    ]


def test_satisfaction_fills_full_1_to_5() -> None:
    data = _build(ReportType.SATISFACTION)
    assert data.rows == [
        {"rating": 1, "count": 0},
        {"rating": 2, "count": 0},
        {"rating": 3, "count": 1},
        {"rating": 4, "count": 0},
        {"rating": 5, "count": 3},
    ]


def test_reopens_rate_computed() -> None:
    data = _build(ReportType.REOPENS)
    assert data.rows == [{"total": 5, "reopened": 2, "reopened_rate_pct": 40.0}]


class _EmptyReopenRepository:
    """Fake с пустым reopens-набором (total=0) — пиннит guard деления на ноль."""

    async def reopen_stats(self, period: StatsPeriod) -> tuple[int, int]:
        return 0, 0


def test_reopens_rate_none_when_total_zero() -> None:
    # Нулевой знаменатель → None (инвариант ADR-0011 Реш.4), не деление на ноль (reports.py).
    repo = cast("AnalyticsRepository", _EmptyReopenRepository())
    data = asyncio.run(build_report(repo, ReportType.REOPENS, _PERIOD, now=_NOW))
    assert data.rows == [{"total": 0, "reopened": 0, "reopened_rate_pct": None}]


def test_operators_resolved_anchor_rows() -> None:
    data = _build(ReportType.OPERATORS)
    assert data.rows == [
        {"operator_id": str(_OP1), "resolved_count": 4, "avg_resolution_minutes": 30.0},
        {"operator_id": str(_OP2), "resolved_count": 1, "avg_resolution_minutes": None},
    ]


def test_csv_header_and_none_as_empty() -> None:
    csv_text = to_csv(_build(ReportType.OPERATORS))
    lines = csv_text.strip().split("\n")
    assert lines[0] == "operator_id,resolved_count,avg_resolution_minutes"
    # None (avg у _OP2) → пустая ячейка.
    assert lines[2] == f"{_OP2},1,"


def test_csv_satisfaction_has_five_rows() -> None:
    csv_text = to_csv(_build(ReportType.SATISFACTION))
    lines = csv_text.strip().split("\n")
    assert lines[0] == "rating,count"
    assert len(lines) == 6  # header + 5 оценок


def test_json_and_csv_share_same_rows() -> None:
    # Один источник истины: pydantic-модель и CSV строятся из одной ReportData.
    data = _build(ReportType.SATISFACTION)
    model = build_report_model(data)
    csv_rows = to_csv(data).strip().split("\n")[1:]  # без заголовка
    assert len(model.rows) == len(csv_rows) == len(data.rows)


def test_no_rating_comment_anywhere_fz152() -> None:
    # ФЗ-152: отчёт удовлетворённости не выгружает rating_comment.
    data = _build(ReportType.SATISFACTION)
    assert all("rating_comment" not in row for row in data.rows)
    assert "rating_comment" not in to_csv(data)
