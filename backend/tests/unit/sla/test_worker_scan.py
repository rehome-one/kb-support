"""Unit-тесты логики скана SLA-воркера (E4-6, #90) — без БД и broker.

`escalate` — чистая логика над списком заявок: хук на каждую не-обработанную,
контекст ноги (first_response/resolution) в событии, seam `already_handled`.
`select_due_tickets` — корректный SQL-предикат (компиляция без БД).
"""

from __future__ import annotations

import datetime
import uuid

from api.sla.worker.hooks import BreachHook, SlaBreachEvent
from api.sla.worker.scan import escalate, scan_and_escalate, select_due_tickets
from api.tickets.enums import TicketStatus
from api.tickets.models import Ticket

UTC = datetime.UTC
NOW = datetime.datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_PAST = NOW - datetime.timedelta(hours=1)
_FUTURE = NOW + datetime.timedelta(hours=1)


def _ticket(**kw: object) -> Ticket:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "number": "SUP-1",
        "type": "OTHER",
        "priority": "normal",
        "team": "support",
        "status": TicketStatus.OPEN.value,
        "first_response_due_at": None,
        "first_responded_at": None,
        "resolution_due_at": None,
        "resolved_at": None,
        "sla_paused_at": None,
    }
    base.update(kw)
    return Ticket(**base)


async def _collect() -> tuple[list[SlaBreachEvent], BreachHook]:
    events: list[SlaBreachEvent] = []

    async def hook(event: SlaBreachEvent) -> None:
        events.append(event)

    return events, hook


async def test_escalate_invokes_hook_per_ticket() -> None:
    events, hook = await _collect()
    tickets = [
        _ticket(number="SUP-1", resolution_due_at=_PAST),
        _ticket(number="SUP-2", first_response_due_at=_PAST),
    ]
    result = await escalate(tickets, NOW, hook=hook)
    assert {e.number for e in result} == {"SUP-1", "SUP-2"}
    assert {e.number for e in events} == {"SUP-1", "SUP-2"}


async def test_escalate_skips_already_handled() -> None:
    events, hook = await _collect()
    tickets = [
        _ticket(number="SUP-1", resolution_due_at=_PAST),
        _ticket(number="SUP-2", resolution_due_at=_PAST),
    ]
    result = await escalate(tickets, NOW, hook=hook, already_handled=lambda t: t.number == "SUP-1")
    assert [e.number for e in result] == ["SUP-2"]
    assert [e.number for e in events] == ["SUP-2"]


async def test_default_seam_handles_nothing() -> None:
    # Дефолтный already_handled (E4 инертен) → ничего не отфильтровано.
    events, hook = await _collect()
    result = await escalate([_ticket(resolution_due_at=_PAST)], NOW, hook=hook)
    assert len(result) == 1


async def test_event_marks_resolution_leg_only() -> None:
    events, hook = await _collect()
    await escalate(
        [_ticket(resolution_due_at=_PAST, first_response_due_at=_FUTURE)], NOW, hook=hook
    )
    assert events[0].resolution_breached is True
    assert events[0].first_response_breached is False


async def test_event_marks_first_response_leg_only() -> None:
    events, hook = await _collect()
    await escalate(
        [_ticket(first_response_due_at=_PAST, resolution_due_at=_FUTURE)], NOW, hook=hook
    )
    assert events[0].first_response_breached is True
    assert events[0].resolution_breached is False


async def test_responded_first_leg_not_breached() -> None:
    # Первый ответ дан → нога закрыта, breach по ней не считается.
    events, hook = await _collect()
    await escalate([_ticket(first_response_due_at=_PAST, first_responded_at=_PAST)], NOW, hook=hook)
    assert events[0].first_response_breached is False


def test_select_due_tickets_predicate_and_order() -> None:
    stmt = select_due_tickets(NOW, batch_limit=500)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "resolution_due_at" in sql
    assert "first_response_due_at" in sql
    assert "NOT IN" in sql  # терминальные статусы исключены
    assert "ORDER BY" in sql
    assert "LIMIT" in sql


class _Result:
    def __init__(self, rows: list[Ticket]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Ticket]:
        return self._rows


class _Session:
    def __init__(self, rows: list[Ticket]) -> None:
        self._rows = rows
        self.statements: list[object] = []

    async def execute(self, stmt: object) -> _Result:
        self.statements.append(stmt)
        return _Result(self._rows)


async def test_scan_and_escalate_uses_query_then_escalates() -> None:
    events, hook = await _collect()
    rows = [_ticket(number="SUP-7", resolution_due_at=_PAST)]
    session = _Session(rows)
    result = await scan_and_escalate(session, now=NOW, hook=hook, batch_limit=10)  # type: ignore[arg-type]
    assert len(session.statements) == 1
    assert [e.number for e in result] == ["SUP-7"]
