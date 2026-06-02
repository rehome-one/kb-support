"""Unit-тесты валидации SLA-схем (#86): форма schedule, TZ, applies_to, PATCH-частичность."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from api.sla.schemas import (
    BusinessHoursInput,
    BusinessHoursUpdate,
    SLAPolicyInput,
    SLAPolicyUpdate,
)


class TestBusinessHoursSchedule:
    def test_valid_schedule_normalized_and_sorted(self) -> None:
        bh = BusinessHoursInput(
            name="РФ будни",
            timezone="Europe/Moscow",
            schedule={"mon": [["14:00", "18:00"], ["09:00", "13:00"]], "sat": []},
        )
        # Интервалы отсортированы по началу; формат нормализован к HH:MM.
        assert bh.schedule["mon"] == [["09:00", "13:00"], ["14:00", "18:00"]]
        assert bh.schedule["sat"] == []

    def test_empty_schedule_ok(self) -> None:
        bh = BusinessHoursInput(name="24/7-кандидат", timezone="UTC")
        assert bh.schedule == {}

    @pytest.mark.parametrize(
        "schedule",
        [
            {"mon": [["18:00", "09:00"]]},  # open >= close
            {"mon": [["09:00", "09:00"]]},  # равны
            {"mon": [["09:00", "13:00"], ["12:00", "18:00"]]},  # пересечение
            {"mon": [["9:00", "18:00"]]},  # не HH:MM
            {"mon": [["09:00", "24:00"]]},  # 24:00 недопустимо
            {"mon": [["09:00"]]},  # не пара
            {"mon": "09:00-18:00"},  # не массив
            {"funday": [["09:00", "18:00"]]},  # неизвестный день
        ],
    )
    def test_invalid_schedule_rejected(self, schedule: object) -> None:
        with pytest.raises(ValidationError):
            BusinessHoursInput.model_validate(
                {"name": "x", "timezone": "Europe/Moscow", "schedule": schedule}
            )

    def test_invalid_timezone_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BusinessHoursInput(name="x", timezone="Mars/Phobos", schedule={})

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            BusinessHoursInput(name="x", timezone="UTC", surprise=1)  # type: ignore[call-arg]


class TestBusinessHoursUpdate:
    def test_partial_only_sets_provided(self) -> None:
        upd = BusinessHoursUpdate(is_active=False)
        assert upd.model_fields_set == {"is_active"}
        assert upd.model_dump(exclude_unset=True) == {"is_active": False}

    def test_timezone_none_skips_validation(self) -> None:
        # timezone не передан → валидатор не падает (частичное обновление).
        upd = BusinessHoursUpdate(name="новое имя")
        assert "timezone" not in upd.model_fields_set

    def test_invalid_timezone_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BusinessHoursUpdate(timezone="Nowhere/Land")


class TestSLAPolicyInput:
    def test_valid_with_applies_to(self) -> None:
        policy = SLAPolicyInput.model_validate(
            {
                "name": "Критичные",
                "applies_to": {"types": ["PAYMENT"], "priorities": ["critical"]},
                "first_response_minutes": 30,
                "resolution_minutes": 240,
                "business_hours_id": str(uuid.uuid4()),
                "priority": 10,
            }
        )
        assert policy.applies_to.types is not None
        assert policy.applies_to.types[0].value == "PAYMENT"

    def test_applies_to_defaults_empty(self) -> None:
        policy = SLAPolicyInput(name="All", first_response_minutes=60, resolution_minutes=480)
        assert policy.applies_to.model_dump(exclude_none=True) == {}

    @pytest.mark.parametrize(
        "applies_to",
        [
            {"types": ["NOT_A_TYPE"]},
            {"priorities": ["urgent"]},
            {"unknown_key": ["x"]},
        ],
    )
    def test_invalid_applies_to_rejected(self, applies_to: object) -> None:
        with pytest.raises(ValidationError):
            SLAPolicyInput.model_validate(
                {
                    "name": "x",
                    "applies_to": applies_to,
                    "first_response_minutes": 60,
                    "resolution_minutes": 480,
                }
            )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"first_response_minutes": 0, "resolution_minutes": 480},
            {"first_response_minutes": 60, "resolution_minutes": -1},
            {"first_response_minutes": 60, "resolution_minutes": 480, "priority": -5},
        ],
    )
    def test_non_positive_values_rejected(self, overrides: dict[str, int]) -> None:
        with pytest.raises(ValidationError):
            SLAPolicyInput.model_validate({"name": "x", **overrides})

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            SLAPolicyInput.model_validate(
                {
                    "name": "x",
                    "first_response_minutes": 60,
                    "resolution_minutes": 480,
                    "surprise": 1,
                }
            )


class TestSLAPolicyUpdate:
    def test_partial_only_sets_provided(self) -> None:
        upd = SLAPolicyUpdate(priority=3)
        assert upd.model_fields_set == {"priority"}

    def test_business_hours_id_explicit_null_is_tracked(self) -> None:
        # Явное зануление (24/7) должно попадать в model_fields_set.
        upd = SLAPolicyUpdate(business_hours_id=None)
        assert "business_hours_id" in upd.model_fields_set

    def test_invalid_partial_minutes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SLAPolicyUpdate(first_response_minutes=0)
