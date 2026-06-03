"""Unit-тесты SLA-метрик (#91): TTFR/TTR + breach через дефолтный REGISTRY."""

from __future__ import annotations

import datetime

from prometheus_client import REGISTRY

from api.tickets.models import Ticket
from api.tickets.sla_metrics import record_first_response, record_resolution

UTC = datetime.UTC
_T0 = datetime.datetime(2026, 6, 3, 9, 0, tzinfo=UTC)


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _ticket(
    *,
    type_: str = "PAYMENT",
    priority: str = "normal",
    team: str | None = "support",
    first_response_due_at: datetime.datetime | None = None,
    first_responded_at: datetime.datetime | None = None,
    resolution_due_at: datetime.datetime | None = None,
    resolved_at: datetime.datetime | None = None,
    sla_paused_seconds: int = 0,
) -> Ticket:
    ticket = Ticket()
    ticket.type = type_
    ticket.priority = priority
    ticket.team = team
    ticket.created_at = _T0
    ticket.first_response_due_at = first_response_due_at
    ticket.first_responded_at = first_responded_at
    ticket.resolution_due_at = resolution_due_at
    ticket.resolved_at = resolved_at
    ticket.sla_paused_seconds = sla_paused_seconds
    return ticket


def _mins(n: int) -> datetime.datetime:
    return _T0 + datetime.timedelta(minutes=n)


class TestFirstResponse:
    def test_ttfr_observed_and_no_breach_within_deadline(self) -> None:
        labels = {"type": "PAYMENT", "priority": "normal", "team": "support"}
        breach_labels = {**labels, "kind": "first_response"}
        ttfr_before = _sample("sla_time_to_first_response_seconds_count", labels)
        breach_before = _sample("sla_breaches_total", breach_labels)

        record_first_response(
            _ticket(first_response_due_at=_mins(60), first_responded_at=_mins(30))
        )

        assert _sample("sla_time_to_first_response_seconds_count", labels) == ttfr_before + 1
        assert _sample("sla_breaches_total", breach_labels) == breach_before  # уложились

    def test_first_response_breach_counted(self) -> None:
        labels = {"type": "CONTRACT", "priority": "high", "team": "legal"}
        breach_labels = {**labels, "kind": "first_response"}
        before = _sample("sla_breaches_total", breach_labels)

        record_first_response(
            _ticket(
                type_="CONTRACT",
                priority="high",
                team="legal",
                first_response_due_at=_mins(60),
                first_responded_at=_mins(90),  # позже дедлайна
            )
        )
        assert _sample("sla_breaches_total", breach_labels) == before + 1


class TestResolution:
    def test_ttr_is_pause_adjusted(self) -> None:
        labels = {"type": "MAINTENANCE", "priority": "low", "team": "support"}
        sum_before = _sample("sla_time_to_resolution_seconds_sum", labels)
        count_before = _sample("sla_time_to_resolution_seconds_count", labels)

        # wall = 120 мин = 7200 с; паузы 1800 с → TTR = 5400 с (business time).
        record_resolution(
            _ticket(
                type_="MAINTENANCE", priority="low", resolved_at=_mins(120), sla_paused_seconds=1800
            )
        )

        assert _sample("sla_time_to_resolution_seconds_count", labels) == count_before + 1
        assert _sample("sla_time_to_resolution_seconds_sum", labels) == sum_before + 5400.0

    def test_resolution_breach_counted(self) -> None:
        labels = {"type": "FRAUD", "priority": "critical", "team": "none"}
        breach_labels = {**labels, "kind": "resolution"}
        before = _sample("sla_breaches_total", breach_labels)

        record_resolution(
            _ticket(
                type_="FRAUD",
                priority="critical",
                team=None,  # → лейбл «none»
                resolution_due_at=_mins(60),
                resolved_at=_mins(90),  # позже дедлайна
            )
        )
        assert _sample("sla_breaches_total", breach_labels) == before + 1

    def test_negative_duration_clamped_to_zero(self) -> None:
        # Паузы больше wall-времени (артефакт) → TTR не отрицателен (max(0, …)).
        labels = {"type": "ACCOUNT", "priority": "normal", "team": "support"}
        sum_before = _sample("sla_time_to_resolution_seconds_sum", labels)
        count_before = _sample("sla_time_to_resolution_seconds_count", labels)

        # wall = 600 с, паузы 1200 с → -600 → клампится в 0.
        record_resolution(_ticket(type_="ACCOUNT", resolved_at=_mins(10), sla_paused_seconds=1200))

        assert _sample("sla_time_to_resolution_seconds_count", labels) == count_before + 1
        assert _sample("sla_time_to_resolution_seconds_sum", labels) == sum_before + 0.0

    def test_no_deadline_records_duration_without_breach(self) -> None:
        labels = {"type": "OTHER", "priority": "normal", "team": "support"}
        res_breach = {**labels, "kind": "resolution"}
        count_before = _sample("sla_time_to_resolution_seconds_count", labels)
        breach_before = _sample("sla_breaches_total", res_breach)

        record_resolution(_ticket(type_="OTHER", resolved_at=_mins(45)))  # без resolution_due_at

        assert _sample("sla_time_to_resolution_seconds_count", labels) == count_before + 1
        assert (
            _sample("sla_breaches_total", res_breach) == breach_before
        )  # нет дедлайна → нет breach
