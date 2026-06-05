"""Unit-тесты моста SLA-breach → движок (#108) — без БД (мок-сессия, monkeypatch).

Покрывают: на breach-событие мост грузит заявку и зовёт run_rules с trigger=
on_sla_breach; исчезнувшая заявка → warning, run_rules НЕ зовётся; структурный
лог breach сохранён (наблюдаемость). Боевой прогон правил — в integration.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.automation import sla_breach
from api.sla.worker.hooks import SlaBreachEvent


def _event(ticket_id: uuid.UUID) -> SlaBreachEvent:
    return SlaBreachEvent(
        ticket_id=ticket_id,
        number="T-1",
        type="OTHER",
        priority="normal",
        team="support",
        first_response_breached=False,
        resolution_breached=True,
    )


class _FakeSession:
    """Мок-сессия: `get` возвращает заданную заявку (или None) и логирует обращения."""

    def __init__(self, ticket: object | None) -> None:
        self._ticket = ticket
        self.got: list[uuid.UUID] = []

    async def get(self, _model: Any, pk: uuid.UUID) -> object | None:
        self.got.append(pk)
        return self._ticket


async def test_bridge_runs_on_sla_breach_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, str]] = []
    logged: list[SlaBreachEvent] = []

    async def fake_run_rules(_session: Any, ticket: object, trigger: str) -> None:
        calls.append((ticket, trigger))

    async def fake_log(event: SlaBreachEvent) -> None:
        logged.append(event)

    monkeypatch.setattr(sla_breach, "run_rules", fake_run_rules)
    monkeypatch.setattr(sla_breach, "on_sla_breach", fake_log)

    ticket = object()
    ticket_id = uuid.uuid4()
    session = _FakeSession(ticket)
    hook = sla_breach.make_sla_breach_hook(cast(AsyncSession, session))
    await hook(_event(ticket_id))

    assert calls == [(ticket, "on_sla_breach")]  # ИМЕННО on_sla_breach, с загруженной заявкой
    assert session.got == [ticket_id]  # заявка загружена по id события
    assert len(logged) == 1  # структурный лог breach сохранён


async def test_bridge_ticket_gone_skips_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def fake_run_rules(*args: Any) -> None:
        calls.append(args)

    async def fake_log(_event: SlaBreachEvent) -> None:
        return None

    monkeypatch.setattr(sla_breach, "run_rules", fake_run_rules)
    monkeypatch.setattr(sla_breach, "on_sla_breach", fake_log)

    session = _FakeSession(None)  # заявка исчезла
    hook = sla_breach.make_sla_breach_hook(cast(AsyncSession, session))
    await hook(_event(uuid.uuid4()))

    assert calls == []  # run_rules НЕ вызван — best-effort, не сбой
