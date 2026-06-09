"""Тесты врезки платёжного пути (E10-7 PR-1, #197): planning/dispatch/clearance-gate.

БД не нужна для config-gate и dispatch: ORM-объекты в памяти, BackgroundTasks реальный,
session — заглушка (gating-ветки её не трогают). Запись clearance-флага в payload —
в integration (нужен реальный repo).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import cast
from unittest import mock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

import api.tickets.payout_dispatch as payout_dispatch
from api.clients.bank import PayoutRequest, PayoutResult
from api.clients.payment_checker import Clearance
from api.config import Settings
from api.tickets.enums import TicketCaseState
from api.tickets.models import Ticket
from api.tickets.payout_dispatch import (
    dispatch_payout,
    maybe_record_clearance,
    maybe_schedule_payout,
)


def _settings(bank_token: str = "m2m-token") -> Settings:
    return Settings(bank_provider_api_token=bank_token, bank_provider_api_base_url="http://bank")


def _ticket(*, case_state: str, approved_amount: Decimal | None = Decimal("100.00")) -> Ticket:
    return Ticket(
        id=uuid.uuid4(),
        number="RH-2026-00042",
        case_state=case_state,
        approved_amount=approved_amount,
    )


# --- maybe_schedule_payout (fire-after releasePayout, U3) ---


def test_schedules_on_new_paid() -> None:
    bg = BackgroundTasks()
    t = _ticket(case_state=TicketCaseState.PAID.value)
    assert maybe_schedule_payout(bg, t, TicketCaseState.PAYOUT_PENDING.value, _settings()) is True
    assert len(bg.tasks) == 1


def test_not_scheduled_when_bank_token_empty() -> None:
    bg = BackgroundTasks()
    t = _ticket(case_state=TicketCaseState.PAID.value)
    assert (
        maybe_schedule_payout(bg, t, TicketCaseState.PAYOUT_PENDING.value, _settings("")) is False
    )
    assert bg.tasks == []


def test_not_scheduled_when_already_paid() -> None:
    # old==PAID → не «только что» перешли (идемпотентный повтор), выплата не дублируется.
    bg = BackgroundTasks()
    t = _ticket(case_state=TicketCaseState.PAID.value)
    assert maybe_schedule_payout(bg, t, TicketCaseState.PAID.value, _settings()) is False
    assert bg.tasks == []


def test_not_scheduled_for_non_paid_transition() -> None:
    bg = BackgroundTasks()
    t = _ticket(case_state=TicketCaseState.PAYOUT_PENDING.value)
    assert maybe_schedule_payout(bg, t, TicketCaseState.DECISION_MADE.value, _settings()) is False
    assert bg.tasks == []


def test_not_scheduled_without_approved_amount() -> None:
    bg = BackgroundTasks()
    t = _ticket(case_state=TicketCaseState.PAID.value, approved_amount=None)
    assert maybe_schedule_payout(bg, t, TicketCaseState.PAYOUT_PENDING.value, _settings()) is False
    assert bg.tasks == []


# --- dispatch_payout (фоновая доставка, best-effort) ---


def _request() -> PayoutRequest:
    return PayoutRequest(
        ticket_id=uuid.uuid4(), amount=Decimal("100.00"), currency="RUB", reference="RH-2026-00042"
    )


async def test_dispatch_runs_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def __init__(self, **_: object) -> None: ...

        async def release_payout(self, request: PayoutRequest) -> PayoutResult:
            return PayoutResult(payment_id="pay-1")

    monkeypatch.setattr(payout_dispatch, "HttpBankProviderClient", _FakeClient)
    await dispatch_payout(_request(), _settings())  # не должно бросить


async def test_dispatch_swallows_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomClient:
        def __init__(self, **_: object) -> None: ...

        async def release_payout(self, request: PayoutRequest) -> PayoutResult:
            raise RuntimeError("bank down")

    monkeypatch.setattr(payout_dispatch, "HttpBankProviderClient", _BoomClient)
    await dispatch_payout(_request(), _settings())  # последний рубеж: не пробрасывает


# --- maybe_record_clearance gating (U4, без БД — ветки не трогают session) ---


class _FakeChecker:
    def __init__(self, result: Clearance | None) -> None:
        self._result = result

    async def check_clearance(self, ticket_id: uuid.UUID) -> Clearance | None:
        return self._result


def _session() -> AsyncSession:
    return cast(AsyncSession, mock.MagicMock())


async def test_clearance_gate_off_when_checker_none() -> None:
    t = _ticket(case_state=TicketCaseState.PAYOUT_PENDING.value)
    assert (
        await maybe_record_clearance(_session(), t, TicketCaseState.DECISION_MADE.value, None)
        is False
    )


async def test_clearance_skipped_when_not_newly_pending() -> None:
    t = _ticket(case_state=TicketCaseState.PAYOUT_PENDING.value)
    checker = _FakeChecker(Clearance(clearable=True, reason=None))
    assert (
        await maybe_record_clearance(_session(), t, TicketCaseState.PAYOUT_PENDING.value, checker)
        is False
    )


async def test_clearance_skipped_on_degradation_none() -> None:
    t = _ticket(case_state=TicketCaseState.PAYOUT_PENDING.value)
    checker = _FakeChecker(None)  # деградация — флаг не пишется, переход не блокируется
    assert (
        await maybe_record_clearance(_session(), t, TicketCaseState.DECISION_MADE.value, checker)
        is False
    )
