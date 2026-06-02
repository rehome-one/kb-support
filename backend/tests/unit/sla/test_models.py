"""Unit-тесты ORM-моделей SLA (E4-1 #85): атрибуты, nullable, repr.

Без БД/сессии — серверные дефолты (is_active/priority/schedule) проверяются в
integration-тесте миграции (там есть flush). Здесь — поведение Python-уровня.
"""

from __future__ import annotations

import uuid

from api.sla.models import BusinessHours, SLAPolicy


def test_business_hours_attributes_and_repr() -> None:
    bh = BusinessHours(
        name="РФ будни 9-18",
        timezone="Europe/Moscow",
        schedule={"mon": [["09:00", "18:00"]], "sat": []},
        is_active=True,
    )
    assert bh.name == "РФ будни 9-18"
    assert bh.timezone == "Europe/Moscow"
    assert bh.schedule["mon"] == [["09:00", "18:00"]]
    assert "BusinessHours" in repr(bh)


def test_sla_policy_attributes_and_repr() -> None:
    bh_id = uuid.uuid4()
    policy = SLAPolicy(
        name="FRAUD fast",
        applies_to={"types": ["FRAUD"], "priorities": ["critical"]},
        first_response_minutes=15,
        resolution_minutes=120,
        business_hours_id=bh_id,
        priority=10,
    )
    assert policy.first_response_minutes == 15
    assert policy.resolution_minutes == 120
    assert policy.applies_to["types"] == ["FRAUD"]
    assert policy.business_hours_id == bh_id
    assert policy.priority == 10
    assert "SLAPolicy" in repr(policy)


def test_sla_policy_business_hours_id_optional_defaults_none() -> None:
    """business_hours_id не задан → None (политика трактуется как 24/7, ADR-0007)."""
    policy = SLAPolicy(
        name="24/7 base",
        applies_to={},
        first_response_minutes=60,
        resolution_minutes=480,
    )
    assert policy.business_hours_id is None
