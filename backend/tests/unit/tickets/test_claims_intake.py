"""Unit-тесты чистой логики приёма claims (E10-5 #195) — без БД."""

from __future__ import annotations

import datetime
from decimal import Decimal

from api.tickets.claims_intake import (
    _compensation_flags,
    _parse_date,
    _parse_decimal,
)

_NOW = datetime.date(2026, 6, 8)


def test_parse_decimal_safe() -> None:
    assert _parse_decimal(100) == Decimal("100.00")
    assert _parse_decimal("12345.67") == Decimal("12345.67")
    assert _parse_decimal(None) is None
    assert _parse_decimal("not-a-number") is None  # битое → None, не падаем
    assert _parse_decimal(True) is None  # bool не сумма


def test_parse_date_safe() -> None:
    assert _parse_date("2026-05-01") == datetime.date(2026, 5, 1)
    assert _parse_date("2026-05-01T10:00:00Z") == datetime.date(2026, 5, 1)
    assert _parse_date("not-a-date") is None
    assert _parse_date(None) is None
    assert _parse_date(123) is None


def test_compensation_over_threshold_flags_appraisal() -> None:
    flags = _compensation_flags({"claim_amount": 50000.01}, now=_NOW)
    assert flags.get("independent_appraisal") is True


def test_compensation_at_or_below_threshold_no_appraisal() -> None:
    assert "independent_appraisal" not in _compensation_flags({"claim_amount": 50000}, now=_NOW)


def test_compensation_outside_window_flags_late() -> None:
    # 20 дней назад > окна 14 дней.
    flags = _compensation_flags({"incident_date": "2026-05-19"}, now=_NOW)
    assert flags.get("late_submission") is True


def test_compensation_within_window_not_late() -> None:
    flags = _compensation_flags({"incident_date": "2026-06-01"}, now=_NOW)  # 7 дней
    assert "late_submission" not in flags


def test_compensation_no_incident_date_not_late() -> None:
    assert "late_submission" not in _compensation_flags({"claim_amount": 100}, now=_NOW)


def test_compensation_evidence_collected_softly() -> None:
    flags = _compensation_flags({"evidence": ["f1", "f2"]}, now=_NOW)
    assert flags["evidence"] == ["f1", "f2"]
