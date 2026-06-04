"""Unit-тесты breach-хука SLA-воркера (E4-6, #90).

Условие ревью #5 (D.5 / NFR-1.3): хук логирует только не-ПДн доменные метки.
Гард: `SlaBreachEvent` не несёт ПДн-полей; лог содержит только id/номер/тип/
приоритет/команду + ноги.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from api.sla.worker import hooks
from api.sla.worker.hooks import SlaBreachEvent, on_sla_breach


def _event(**kw: object) -> SlaBreachEvent:
    base: dict[str, object] = {
        "ticket_id": uuid.uuid4(),
        "number": "SUP-9",
        "type": "PAYMENT",
        "priority": "high",
        "team": "support",
        "first_response_breached": True,
        "resolution_breached": False,
    }
    base.update(kw)
    return SlaBreachEvent(**base)  # type: ignore[arg-type]


def test_event_carries_no_pii_fields() -> None:
    names = {f.name for f in dataclasses.fields(SlaBreachEvent)}
    assert not (names & {"subject", "description", "requester_id", "email", "phone", "transcript"})


async def test_hook_logs_domain_fields_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_warning(msg: str, *args: object) -> None:
        captured["msg"] = msg
        captured["args"] = args

    monkeypatch.setattr(hooks._logger, "warning", fake_warning)
    event = _event(first_response_breached=True, resolution_breached=True)
    await on_sla_breach(event)

    args = captured["args"]
    assert isinstance(args, tuple)
    assert event.ticket_id in args
    assert "SUP-9" in args
    assert "PAYMENT" in args
    # legs-строка отражает обе нарушенные ноги.
    assert "first_response,resolution" in args


async def test_hook_legs_dash_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        hooks._logger,
        "warning",
        lambda msg, *args: captured.update(args=args),
    )
    await on_sla_breach(_event(first_response_breached=False, resolution_breached=False))
    assert "-" in captured["args"]  # type: ignore[operator]
