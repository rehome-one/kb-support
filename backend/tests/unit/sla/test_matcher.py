"""Unit-тесты выбора SLA-политики (#87): конъюнкция applies_to, вариант A для ролей."""

from __future__ import annotations

from typing import Any

from api.sla.matcher import select_policy
from api.sla.models import SLAPolicy


def _policy(name: str, applies_to: dict[str, Any], priority: int = 0) -> SLAPolicy:
    return SLAPolicy(
        name=name,
        applies_to=applies_to,
        first_response_minutes=30,
        resolution_minutes=240,
        priority=priority,
    )


def test_catch_all_matches() -> None:
    policy = _policy("all", {})
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="low") is policy


def test_types_only() -> None:
    policy = _policy("payments", {"types": ["PAYMENT", "CONTRACT"]})
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="low") is policy
    assert select_policy([policy], ticket_type="FRAUD", ticket_priority="low") is None


def test_priorities_only() -> None:
    policy = _policy("urgent", {"priorities": ["critical"]})
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="critical") is policy
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="low") is None


def test_type_and_priority_conjunction() -> None:
    policy = _policy("both", {"types": ["PAYMENT"], "priorities": ["critical"]})
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="critical") is policy
    # Одно измерение не совпало → не матчится.
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="low") is None
    assert select_policy([policy], ticket_type="FRAUD", ticket_priority="critical") is None


def test_requester_roles_nonempty_blocks_match_variant_a() -> None:
    # Вариант A: политика с НЕпустым requester_roles не матчится на создании.
    policy = _policy("role-specific", {"requester_roles": ["tenant"]})
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="low") is None


def test_requester_roles_empty_list_is_wildcard() -> None:
    # Пустой requester_roles = отсутствие ограничения → матчится.
    policy = _policy("empty-roles", {"requester_roles": []})
    assert select_policy([policy], ticket_type="PAYMENT", ticket_priority="low") is policy


def test_no_match_returns_none() -> None:
    policy = _policy("payments", {"types": ["PAYMENT"]})
    assert select_policy([policy], ticket_type="LISTING", ticket_priority="low") is None


def test_first_match_wins_in_given_order() -> None:
    # Порядок задаётся вызывающим (list_active: priority desc, id). Матчер берёт первую.
    high = _policy("high", {"types": ["PAYMENT"]}, priority=100)
    low = _policy("low", {}, priority=0)
    chosen = select_policy([high, low], ticket_type="PAYMENT", ticket_priority="low")
    assert chosen is high
    # Если высокоприоритетная не подходит — берётся следующая подходящая.
    chosen2 = select_policy([high, low], ticket_type="LISTING", ticket_priority="low")
    assert chosen2 is low


def test_empty_policy_list() -> None:
    assert select_policy([], ticket_type="PAYMENT", ticket_priority="low") is None
