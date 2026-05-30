"""Unit-тесты журнала действий: diff-логика record_changes (без БД)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from api.tickets.history import (
    TicketHistory,
    TicketHistoryAction,
    _to_jsonable,
    record_changes,
)


class _FakeRecorder:
    """Собирает вызовы record() вместо записи в БД (декаплинг diff-логики)."""

    def __init__(self) -> None:
        self.calls: list[
            tuple[TicketHistoryAction, dict[str, Any] | None, dict[str, Any] | None]
        ] = []

    async def record(
        self,
        ticket_id: uuid.UUID,
        actor_id: uuid.UUID,
        action: TicketHistoryAction,
        *,
        from_value: dict[str, Any] | None = None,
        to_value: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append((action, from_value, to_value))


@pytest.mark.asyncio
async def test_record_changes_emits_only_changed_tracked_fields() -> None:
    rec = _FakeRecorder()
    new_assignee = uuid.uuid4()
    await record_changes(
        rec,
        uuid.uuid4(),
        uuid.uuid4(),
        {"status": "NEW", "assignee_id": None, "priority": "normal", "tags": []},
        {"status": "OPEN", "assignee_id": new_assignee, "priority": "normal", "tags": ["urgent"]},
    )
    actions = [call[0] for call in rec.calls]
    assert TicketHistoryAction.STATUS_CHANGED in actions
    assert TicketHistoryAction.REASSIGNED in actions
    assert TicketHistoryAction.TAGS_UPDATED in actions
    assert TicketHistoryAction.PRIORITY_CHANGED not in actions  # не менялось


@pytest.mark.asyncio
async def test_record_changes_coerces_uuid_to_str() -> None:
    rec = _FakeRecorder()
    new_assignee = uuid.uuid4()
    await record_changes(
        rec,
        uuid.uuid4(),
        uuid.uuid4(),
        {"assignee_id": None},
        {"assignee_id": new_assignee},
    )
    (_, from_value, to_value) = rec.calls[0]
    assert from_value == {"assignee_id": None}
    assert to_value == {"assignee_id": str(new_assignee)}


@pytest.mark.asyncio
async def test_record_changes_no_changes_emits_nothing() -> None:
    rec = _FakeRecorder()
    same: dict[str, Any] = {"status": "NEW", "assignee_id": None, "priority": "normal", "tags": []}
    await record_changes(rec, uuid.uuid4(), uuid.uuid4(), same, dict(same))
    assert rec.calls == []


@pytest.mark.asyncio
async def test_record_changes_ignores_untracked_fields() -> None:
    rec = _FakeRecorder()
    await record_changes(rec, uuid.uuid4(), uuid.uuid4(), {"subject": "a"}, {"subject": "b"})
    assert rec.calls == []


def test_to_jsonable_coercions() -> None:
    value = uuid.uuid4()
    assert _to_jsonable(value) == str(value)
    assert _to_jsonable(TicketHistoryAction.CREATED) == "created"
    assert _to_jsonable("plain") == "plain"
    assert _to_jsonable(None) is None
    assert _to_jsonable([1, 2]) == [1, 2]


def test_history_repr() -> None:
    row = TicketHistory(ticket_id=uuid.uuid4(), actor_id=uuid.uuid4(), action="created")
    rendered = repr(row)
    assert rendered.startswith("<TicketHistory ")
    assert "created" in rendered


def test_action_enum_values() -> None:
    assert TicketHistoryAction.CREATED.value == "created"
    assert {a.value for a in TicketHistoryAction} >= {
        "created",
        "status_changed",
        "reassigned",
        "priority_changed",
        "tags_updated",
        "message_added",
    }
