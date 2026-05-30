"""Unit-тесты схем action-запросов (без БД)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from api.tickets.schemas import (
    AssignInput,
    EscalateInput,
    RateInput,
    ReopenInput,
    ResolveInput,
)


def test_assign_requires_assignee_id() -> None:
    with pytest.raises(ValidationError):
        AssignInput.model_validate({})


def test_assign_valid_team_optional() -> None:
    payload = AssignInput(assignee_id=uuid.uuid4())
    assert payload.team is None


def test_assign_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        AssignInput.model_validate({"assignee_id": str(uuid.uuid4()), "status": "OPEN"})


def test_rate_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        RateInput.model_validate({"rating": 0})
    with pytest.raises(ValidationError):
        RateInput.model_validate({"rating": 6})


def test_rate_requires_rating() -> None:
    with pytest.raises(ValidationError):
        RateInput.model_validate({"comment": "ok"})


def test_rate_comment_max_length() -> None:
    with pytest.raises(ValidationError):
        RateInput.model_validate({"rating": 3, "comment": "x" * 2001})


def test_optional_text_inputs_default_none() -> None:
    assert EscalateInput().reason is None
    assert ResolveInput().resolution_note is None
    assert ReopenInput().reason is None
