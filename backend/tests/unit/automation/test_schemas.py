"""Unit-тесты схем admin CRUD автоматизации (E5-2 #104) — без БД.

Покрывают: типизацию conditions (домены + extra forbid), дискриминированные actions
с cross-field (assign-стратегии), min_length actions/tags, alias `order`↔`apply_order`
(оба направления — условие 2 ревью).
"""

from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.automation.schemas import (
    AutomationRuleInput,
    AutomationRuleRead,
    AutomationRuleUpdate,
    SetStatusAction,
)
from api.tickets.enums import TicketStatus

_OP = uuid.uuid4()


def _input(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "rule",
        "trigger": "on_create",
        "actions": [{"action": "set_status", "params": {"status": "OPEN"}}],
    }
    base.update(kw)
    return base


# --- conditions ---


def test_conditions_accept_known_domains() -> None:
    rule = AutomationRuleInput.model_validate(
        _input(
            conditions={
                "types": ["FRAUD"],
                "priorities": ["critical"],
                "channels": ["AI_CHAT"],
                "keywords": ["мошенничество"],
            }
        )
    )
    assert rule.conditions.types is not None


def test_conditions_reject_unknown_type() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(_input(conditions={"types": ["NOPE"]}))


def test_conditions_reject_extra_key() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(_input(conditions={"weird": 1}))


def test_empty_conditions_ok_wildcard() -> None:
    rule = AutomationRuleInput.model_validate(_input(conditions={}))
    assert rule.conditions.types is None


# --- actions: discriminated union + cross-field ---


def test_action_discriminated_by_action_field() -> None:
    rule = AutomationRuleInput.model_validate(
        _input(actions=[{"action": "set_status", "params": {"status": "OPEN"}}])
    )
    assert isinstance(rule.actions[0], SetStatusAction)


def test_assign_direct_requires_operator_id() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(
            _input(actions=[{"action": "assign", "params": {"strategy": "direct"}}])
        )


def test_assign_strategy_requires_team() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(
            _input(actions=[{"action": "assign", "params": {"strategy": "least_load"}}])
        )


def test_assign_direct_with_operator_ok() -> None:
    rule = AutomationRuleInput.model_validate(
        _input(
            actions=[
                {"action": "assign", "params": {"strategy": "direct", "operator_id": str(_OP)}}
            ]
        )
    )
    assert rule.actions[0].action.value == "assign"


def test_add_tag_rejects_empty_tags() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(
            _input(actions=[{"action": "add_tag", "params": {"tags": []}}])
        )


def test_actions_require_at_least_one() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(_input(actions=[]))


def test_unknown_action_rejected() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(
            _input(actions=[{"action": "delete_ticket", "params": {}}])
        )


# --- order ↔ apply_order alias (условие 2) ---


def test_order_alias_in_on_input() -> None:
    rule = AutomationRuleInput.model_validate(_input(order=5))
    assert rule.order == 5


def test_order_alias_out_on_read() -> None:
    # Read из ORM-подобного объекта с колонкой apply_order → JSON-поле order.
    now = datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC)
    obj = SimpleNamespace(
        id=uuid.uuid4(),
        name="r",
        trigger="on_create",
        conditions={},
        actions=[{"action": "set_status", "params": {"status": "OPEN"}}],
        is_active=True,
        apply_order=5,
        created_at=now,
        updated_at=now,
    )
    read = AutomationRuleRead.model_validate(obj)
    assert read.order == 5
    assert read.model_dump()["order"] == 5


# --- временные условия time_based (#110, footgun-валидатор) ---


def test_time_fields_accepted_on_time_based() -> None:
    rule = AutomationRuleInput.model_validate(
        _input(
            trigger="time_based",
            conditions={"statuses": ["PENDING"], "inactive_minutes": 4320},
            actions=[{"action": "set_status", "params": {"status": "CLOSED"}}],
        )
    )
    assert rule.conditions.inactive_minutes == 4320
    assert rule.conditions.statuses is not None


def test_unanswered_minutes_accepted_on_time_based() -> None:
    rule = AutomationRuleInput.model_validate(
        _input(trigger="time_based", conditions={"unanswered_minutes": 60})
    )
    assert rule.conditions.unanswered_minutes == 60


def test_time_fields_rejected_on_non_time_based() -> None:
    with pytest.raises(ValidationError, match="time_based"):
        AutomationRuleInput.model_validate(
            _input(trigger="on_create", conditions={"inactive_minutes": 60})
        )


def test_time_based_requires_a_time_field() -> None:
    with pytest.raises(ValidationError, match="inactive_minutes или unanswered_minutes"):
        AutomationRuleInput.model_validate(
            _input(trigger="time_based", conditions={"statuses": ["PENDING"]})
        )


def test_time_field_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AutomationRuleInput.model_validate(
            _input(trigger="time_based", conditions={"inactive_minutes": 0})
        )


def test_statuses_dimension_accepted() -> None:
    rule = AutomationRuleInput.model_validate(_input(conditions={"statuses": ["PENDING", "OPEN"]}))
    assert rule.conditions.statuses == [TicketStatus.PENDING, TicketStatus.OPEN]


def test_update_time_field_rejected_when_trigger_non_time_based() -> None:
    with pytest.raises(ValidationError, match="time_based"):
        AutomationRuleUpdate.model_validate(
            {"trigger": "on_update", "conditions": {"unanswered_minutes": 30}}
        )


def test_update_time_field_allowed_without_trigger() -> None:
    # trigger не передан (частичное обновление) → валидатор пропускает (триггер не меняется).
    upd = AutomationRuleUpdate.model_validate({"conditions": {"inactive_minutes": 30}})
    assert upd.conditions is not None and upd.conditions.inactive_minutes == 30
