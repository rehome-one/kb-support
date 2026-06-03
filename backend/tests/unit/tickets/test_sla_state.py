"""Unit-тесты расчёта состояния SLA (#89): ноги, порог 20%, пауза, terminal."""

from __future__ import annotations

import datetime

from api.tickets.sla_state import compute_sla_state, is_resolution_breached

UTC = datetime.UTC
_T0 = datetime.datetime(2026, 6, 3, 9, 0, tzinfo=UTC)


def _m(n: int) -> datetime.datetime:
    return _T0 + datetime.timedelta(minutes=n)


def _state(
    now: datetime.datetime,
    *,
    fr_due: datetime.datetime | None = None,
    fr_at: datetime.datetime | None = None,
    res_due: datetime.datetime | None = None,
    res_at: datetime.datetime | None = None,
    paused_at: datetime.datetime | None = None,
) -> str:
    return compute_sla_state(
        now,
        created_at=_T0,
        first_response_due_at=fr_due,
        first_responded_at=fr_at,
        resolution_due_at=res_due,
        resolved_at=res_at,
        sla_paused_at=paused_at,
    )


class TestComputeSlaState:
    def test_none_without_deadlines(self) -> None:
        assert _state(_m(10)) == "none"

    def test_ok_far_from_deadline(self) -> None:
        assert _state(_m(10), res_due=_m(100)) == "ok"

    def test_approaching_boundary_strict(self) -> None:
        # Окно 100 мин → approaching при остатке <20 мин (т.е. now > 80 мин).
        assert _state(_m(80), res_due=_m(100)) == "ok"  # ровно 20 мин остатка — ещё ok
        assert _state(_m(81), res_due=_m(100)) == "approaching"  # <20 мин остатка

    def test_breached_after_deadline(self) -> None:
        assert _state(_m(101), res_due=_m(100)) == "breached"
        assert _state(_m(100), res_due=_m(100)) == "breached"  # ровно дедлайн = breached

    def test_first_responded_on_time_makes_leg_ok(self) -> None:
        # Ответ дан вовремя → нога первого ответа ok, даже если now далеко за дедлайном.
        assert _state(_m(500), fr_due=_m(60), fr_at=_m(30)) == "ok"

    def test_first_responded_late_is_breached(self) -> None:
        assert _state(_m(500), fr_due=_m(60), fr_at=_m(90)) == "breached"

    def test_resolution_pause_freezes_before_deadline(self) -> None:
        # Пауза началась до дедлайна (40 мин) → даже спустя время не breached.
        assert _state(_m(500), res_due=_m(100), paused_at=_m(40)) == "ok"

    def test_resolution_pause_after_deadline_is_breached(self) -> None:
        # Пауза началась уже после дедлайна → состояние заморожено как breached.
        assert _state(_m(500), res_due=_m(100), paused_at=_m(120)) == "breached"

    def test_resolved_on_time_ok(self) -> None:
        assert _state(_m(500), res_due=_m(100), res_at=_m(90)) == "ok"

    def test_resolved_late_breached(self) -> None:
        assert _state(_m(500), res_due=_m(100), res_at=_m(110)) == "breached"

    def test_combination_takes_worst(self) -> None:
        # Первый ответ approaching (окно 100, now 90) + решение ok (окно 1000) → approaching.
        assert _state(_m(90), fr_due=_m(100), res_due=_m(1000)) == "approaching"
        # Первый ответ ok (ответили) + решение breached → breached.
        assert _state(_m(500), fr_due=_m(100), fr_at=_m(10), res_due=_m(100)) == "breached"

    def test_terminal_closed_without_reply_is_breached_historical(self) -> None:
        # CLOSED без публичного ответа: нога первого ответа просрочена навсегда (историч. правда).
        assert _state(_m(500), fr_due=_m(60)) == "breached"

    def test_window_non_positive_skips_approaching(self) -> None:
        # Дедлайн ≤ created_at → окно ≤ 0: approaching не применяем, только ok/breached.
        same = compute_sla_state(
            _T0 - datetime.timedelta(minutes=1),
            created_at=_T0,
            first_response_due_at=None,
            first_responded_at=None,
            resolution_due_at=_T0,
            resolved_at=None,
            sla_paused_at=None,
        )
        assert same == "ok"  # now до дедлайна, окно 0 → не approaching


class TestIsResolutionBreached:
    def test_none_due(self) -> None:
        assert (
            is_resolution_breached(
                _m(10), resolution_due_at=None, resolved_at=None, sla_paused_at=None
            )
            is False
        )

    def test_unresolved_overdue(self) -> None:
        assert (
            is_resolution_breached(
                _m(101), resolution_due_at=_m(100), resolved_at=None, sla_paused_at=None
            )
            is True
        )

    def test_paused_before_deadline_not_breached(self) -> None:
        assert (
            is_resolution_breached(
                _m(500), resolution_due_at=_m(100), resolved_at=None, sla_paused_at=_m(40)
            )
            is False
        )

    def test_paused_after_deadline_breached(self) -> None:
        assert (
            is_resolution_breached(
                _m(500), resolution_due_at=_m(100), resolved_at=None, sla_paused_at=_m(120)
            )
            is True
        )

    def test_resolved_on_time(self) -> None:
        assert (
            is_resolution_breached(
                _m(500), resolution_due_at=_m(100), resolved_at=_m(90), sla_paused_at=None
            )
            is False
        )

    def test_resolved_late(self) -> None:
        assert (
            is_resolution_breached(
                _m(500), resolution_due_at=_m(100), resolved_at=_m(110), sla_paused_at=None
            )
            is True
        )
