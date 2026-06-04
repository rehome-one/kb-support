"""Unit-guard: домены enum автоматизации = контракт (ТЗ §3.9, docs/openapi.yaml).

Контракт immutable — источник правды домена (Issue #5). Если enum разойдётся с
`AutomationRule.trigger` / `actions[].action` в openapi, тест упадёт.
"""

from __future__ import annotations

from api.automation.enums import AutomationActionType, AutomationTrigger
from api.automation.models import AutomationRule


def test_trigger_domain_matches_contract() -> None:
    assert {t.value for t in AutomationTrigger} == {
        "on_create",
        "on_update",
        "on_sla_breach",
        "time_based",
    }


def test_action_domain_matches_contract() -> None:
    assert {a.value for a in AutomationActionType} == {
        "assign",
        "set_status",
        "set_priority",
        "add_tag",
        "notify",
        "escalate",
        "create_service_order",
    }


def test_rule_repr_is_safe() -> None:
    rule = AutomationRule(name="fraud-routing", trigger=AutomationTrigger.ON_CREATE.value)
    text = repr(rule)
    assert "fraud-routing" in text
    assert "on_create" in text
