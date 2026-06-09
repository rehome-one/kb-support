"""Тесты fire-after врезки решения (E10-7 PR-2, #197): ledger + доставка в ЛК."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks

import api.tickets.decision_dispatch as dd
from api.clients.financial_ledger import LedgerEntry, LedgerResult
from api.clients.lk_notify import DecisionNotification
from api.config import Settings
from api.tickets.models import Ticket


def _settings(*, ledger: str = "tok", platform: str = "tok") -> Settings:
    return Settings(
        financial_ledger_api_token=ledger,
        financial_ledger_api_base_url="http://ledger",
        platform_api_token=platform,
        platform_api_base_url="http://platform",
    )


def _ticket(*, decision: str | None = "FULL") -> Ticket:
    return Ticket(
        id=uuid.uuid4(),
        number="RH-2026-00042",
        requester_id=uuid.uuid4(),
        decision=decision,
        approved_amount=Decimal("100.00"),
        decision_reason="reason",
    )


# --- ledger ---


def test_ledger_scheduled_when_enabled() -> None:
    bg = BackgroundTasks()
    assert dd.maybe_schedule_ledger(bg, _ticket(), _settings()) is True
    assert len(bg.tasks) == 1


def test_ledger_not_scheduled_when_off() -> None:
    bg = BackgroundTasks()
    assert dd.maybe_schedule_ledger(bg, _ticket(), _settings(ledger="")) is False
    assert bg.tasks == []


def test_ledger_not_scheduled_without_decision() -> None:
    bg = BackgroundTasks()
    assert dd.maybe_schedule_ledger(bg, _ticket(decision=None), _settings()) is False
    assert bg.tasks == []


# --- доставка в ЛК ---


def test_delivery_scheduled_when_enabled() -> None:
    bg = BackgroundTasks()
    assert dd.maybe_schedule_decision_delivery(bg, _ticket(), _settings()) is True
    assert len(bg.tasks) == 1


def test_delivery_not_scheduled_when_platform_off() -> None:
    bg = BackgroundTasks()
    assert dd.maybe_schedule_decision_delivery(bg, _ticket(), _settings(platform="")) is False
    assert bg.tasks == []


def test_delivery_not_scheduled_without_decision() -> None:
    bg = BackgroundTasks()
    assert dd.maybe_schedule_decision_delivery(bg, _ticket(decision=None), _settings()) is False
    assert bg.tasks == []


# --- фоновая доставка never-raises ---


async def test_dispatch_ledger_swallows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def __init__(self, **_: object) -> None: ...

        async def record_entry(self, entry: LedgerEntry) -> LedgerResult:
            raise RuntimeError("ledger down")

    monkeypatch.setattr(dd, "HttpFinancialLedgerClient", _Boom)
    entry = LedgerEntry(
        ticket_id=uuid.uuid4(), decision="FULL", amount=Decimal("1.00"), reference="R"
    )
    await dd.dispatch_ledger(entry, _settings())  # не пробрасывает


async def test_dispatch_delivery_swallows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def __init__(self, **_: object) -> None: ...

        async def notify_decision(self, notification: DecisionNotification) -> None:
            raise RuntimeError("platform down")

    monkeypatch.setattr(dd, "HttpLkNotifyClient", _Boom)
    note = DecisionNotification(
        ticket_id=uuid.uuid4(),
        requester_id=uuid.uuid4(),
        decision="FULL",
        approved_amount=None,
        reason=None,
    )
    await dd.dispatch_decision_delivery(note, _settings())  # не пробрасывает


async def test_dispatch_ledger_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Ok:
        def __init__(self, **_: object) -> None: ...

        async def record_entry(self, entry: LedgerEntry) -> LedgerResult:
            return LedgerResult(entry_id="e-1")

    monkeypatch.setattr(dd, "HttpFinancialLedgerClient", _Ok)
    entry = LedgerEntry(
        ticket_id=uuid.uuid4(), decision="FULL", amount=Decimal("1.00"), reference="R"
    )
    await dd.dispatch_ledger(entry, _settings())  # успешный путь (info-лог)


async def test_dispatch_delivery_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Ok:
        def __init__(self, **_: object) -> None: ...

        async def notify_decision(self, notification: DecisionNotification) -> None:
            return None

    monkeypatch.setattr(dd, "HttpLkNotifyClient", _Ok)
    note = DecisionNotification(
        ticket_id=uuid.uuid4(),
        requester_id=uuid.uuid4(),
        decision="FULL",
        approved_amount=None,
        reason=None,
    )
    await dd.dispatch_decision_delivery(note, _settings())  # успешный путь (info-лог)
