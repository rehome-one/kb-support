"""Unit-тесты best-effort обёртки и seam-исполнителей (E5-4 #106) — без БД.

Покрывают: диспетчеризацию, изоляцию сбоя (метрика + не проброс), наблюдаемый
недо-резолв assign-стратегии (deferred-метрика), seam notify/create_service_order
без ПДн. Пути, требующие БД (реальные мутации + history), — в integration.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.automation import actions


def _ticket() -> Any:
    # ПДн-поле subject заполнено намеренно — проверяем, что seam его НЕ логирует.
    return SimpleNamespace(id=uuid.uuid4(), subject="секретное описание ПДн", tags=[])


async def _apply(action: dict[str, Any]) -> bool:
    return await actions.apply_action(
        cast(AsyncSession, object()),  # session не используется в seam/deferred-путях
        _ticket(),
        action,
        rule_id=uuid.uuid4(),
        trigger="on_create",
    )


async def test_unknown_action_fails_and_records_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        actions,
        "record_rule_failure",
        lambda **kw: calls.append((kw["rule_id"], kw["action"], kw["trigger"])),
    )
    ok = await _apply({"action": "delete_ticket", "params": {}})
    assert ok is False
    assert len(calls) == 1 and calls[0][1] == "delete_ticket"


async def test_invalid_params_isolated_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # notify без recipient → ValidationError в исполнителе → False + метрика, не проброс.
    failures: list[str] = []
    monkeypatch.setattr(actions, "record_rule_failure", lambda **kw: failures.append(kw["action"]))
    ok = await _apply({"action": "notify", "params": {}})
    assert ok is False
    assert failures == ["notify"]


async def test_assign_strategy_deferred_is_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    deferred: list[tuple[str, str]] = []
    monkeypatch.setattr(
        actions,
        "record_action_deferred",
        lambda **kw: deferred.append((kw["action"], kw["reason"])),
    )
    # least_load (team задан) валиден по схеме, но БЕЗ пула (#77 не провижинен) →
    # резолвер возвращает None → наблюдаемая отсрочка (не сбой).
    ok = await _apply({"action": "assign", "params": {"strategy": "least_load", "team": "support"}})
    assert ok is True  # недо-резолв — не сбой, а наблюдаемая отсрочка
    assert deferred == [("assign", "strategy_least_load_no_pool")]


async def test_notify_seam_logs_without_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[tuple[Any, ...]] = []
    monkeypatch.setattr(actions._logger, "info", lambda msg, *args: logged.append((msg, *args)))
    ok = await _apply({"action": "notify", "params": {"recipient": "supervisor"}})
    assert ok is True
    # Лог намерения: только не-ПДн метки; subject заявки не должен утечь.
    flat = " ".join(str(x) for row in logged for x in row)
    assert "supervisor" in flat
    assert "секретное описание" not in flat


async def test_create_service_order_seam_logs_without_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[tuple[Any, ...]] = []
    monkeypatch.setattr(actions._logger, "info", lambda msg, *args: logged.append((msg, *args)))
    ok = await _apply(
        {"action": "create_service_order", "params": {"collaborator_category": "cleaning"}}
    )
    assert ok is True
    flat = " ".join(str(x) for row in logged for x in row)
    assert "cleaning" in flat
    assert "секретное описание" not in flat
