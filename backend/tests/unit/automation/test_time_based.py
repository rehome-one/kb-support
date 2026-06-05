"""Unit-тесты чистого временного предиката time_based (#110) — без БД.

Покрывают `time_predicate_satisfied` (чистое зеркало SQL-клаузы): inactive/unanswered/
конъюнкция/границы `<=`/None-поля/без временных полей/защита от bool в JSONB. Согласование
зеркала с SQL-клаузой на реальной БД — integration `test_time_based_scan`.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import false

from api.automation.time_based import time_predicate_clause, time_predicate_satisfied

_NOW = datetime.datetime(2026, 6, 5, 12, 0, tzinfo=datetime.UTC)


def _ticket(**over: Any) -> Any:
    base = {
        "updated_at": _NOW,
        "created_at": _NOW,
        "first_responded_at": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_no_time_fields_is_false() -> None:
    # Без порога правило не матчит ничего (защитный дефолт; схема требует ≥1 поля).
    assert time_predicate_satisfied(_ticket(), {}, _NOW) is False
    assert time_predicate_satisfied(_ticket(), {"statuses": ["PENDING"]}, _NOW) is False


def test_no_time_fields_clause_is_false() -> None:
    # Защитный дефолт SQL-клаузы: без временных полей → false() (ничего не матчит).
    assert time_predicate_clause({}, _NOW).compare(false())
    assert time_predicate_clause({"statuses": ["PENDING"]}, _NOW).compare(false())


def test_inactive_boundary_inclusive() -> None:
    cond = {"inactive_minutes": 60}
    # ровно на границе: updated_at == now - 60м → срабатывает (<=)
    assert time_predicate_satisfied(
        _ticket(updated_at=_NOW - datetime.timedelta(minutes=60)), cond, _NOW
    )
    # на секунду свежее границы → не срабатывает
    assert not time_predicate_satisfied(
        _ticket(updated_at=_NOW - datetime.timedelta(minutes=60) + datetime.timedelta(seconds=1)),
        cond,
        _NOW,
    )


def test_inactive_fresh_ticket_not_matched() -> None:
    assert not time_predicate_satisfied(_ticket(updated_at=_NOW), {"inactive_minutes": 60}, _NOW)


def test_unanswered_matches_only_when_no_first_response_and_old() -> None:
    cond = {"unanswered_minutes": 30}
    old = _NOW - datetime.timedelta(minutes=30)
    assert time_predicate_satisfied(_ticket(created_at=old, first_responded_at=None), cond, _NOW)
    # первый ответ уже был → не unanswered
    assert not time_predicate_satisfied(
        _ticket(created_at=old, first_responded_at=_NOW), cond, _NOW
    )
    # создана недавно → ещё не дозрела
    assert not time_predicate_satisfied(
        _ticket(created_at=_NOW, first_responded_at=None), cond, _NOW
    )


def test_conjunction_requires_both() -> None:
    cond = {"inactive_minutes": 60, "unanswered_minutes": 30}
    old_inactive = _NOW - datetime.timedelta(minutes=60)
    old_created = _NOW - datetime.timedelta(minutes=30)
    # оба удовлетворены
    assert time_predicate_satisfied(
        _ticket(updated_at=old_inactive, created_at=old_created, first_responded_at=None),
        cond,
        _NOW,
    )
    # только inactive (есть первый ответ) → не выбирается
    assert not time_predicate_satisfied(
        _ticket(updated_at=old_inactive, created_at=old_created, first_responded_at=_NOW),
        cond,
        _NOW,
    )
    # только unanswered (свежий updated_at) → не выбирается
    assert not time_predicate_satisfied(
        _ticket(updated_at=_NOW, created_at=old_created, first_responded_at=None),
        cond,
        _NOW,
    )


def test_bool_in_jsonb_is_ignored() -> None:
    # bool — не валидный порог (защита от мусора в сыром JSONB): трактуется как отсутствие.
    assert time_predicate_satisfied(_ticket(updated_at=_NOW), {"inactive_minutes": True}, _NOW) is (
        False
    )
