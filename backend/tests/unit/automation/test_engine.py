"""Unit-тесты оркестратора run_rules (E5-5 #107) — мок-сессия/repo/apply_action, без БД.

Покрывают: load→match→исполнение в порядке; изоляцию сбоя действия (rollback+refresh,
остальные идут); never-raise при сбое оркестрации и savepoint-финализации; пустые
правила = no-op; цепочку действий одного правила в порядке.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.automation import engine
from api.automation.models import AutomationRule


async def _run(session: Any, ticket: Any, trigger: str) -> None:
    await engine.run_rules(cast(AsyncSession, session), ticket, trigger)


def _rule(name: str, conditions: dict[str, Any], actions: list[dict[str, Any]]) -> AutomationRule:
    return AutomationRule(name=name, trigger="on_create", conditions=conditions, actions=actions)


def _ticket(**over: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "subject": "s",
        "description": "d",
        "type": "FRAUD",
        "priority": "critical",
        "channel": "AI_CHAT",
        "status": "PENDING",
    }
    base.update(over)
    return SimpleNamespace(**base)


class _FakeSavepoint:
    def __init__(self, fail_commit: bool = False) -> None:
        self.committed = False
        self.rolledback = False
        self._fail_commit = fail_commit

    async def commit(self) -> None:
        if self._fail_commit:
            raise RuntimeError("commit boom")
        self.committed = True

    async def rollback(self) -> None:
        self.rolledback = True


class _FakeSession:
    def __init__(self, savepoint_factory: Any = _FakeSavepoint) -> None:
        self._spf = savepoint_factory
        self.savepoints: list[Any] = []
        self.refreshed: list[Any] = []

    async def begin_nested(self) -> Any:
        sp = self._spf()
        self.savepoints.append(sp)
        return sp

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)


class _FakeRepo:
    def __init__(self, rules: list[AutomationRule]) -> None:
        self._rules = rules

    async def list_active(self, trigger: str) -> list[AutomationRule]:
        return self._rules


def _patch(monkeypatch: pytest.MonkeyPatch, rules: list[AutomationRule], apply: Any) -> None:
    monkeypatch.setattr(engine, "AutomationRuleRepository", lambda session: _FakeRepo(rules))
    monkeypatch.setattr(engine, "apply_action", apply)


async def test_applies_only_matched_rules_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    r1 = _rule("r1", {"types": ["FRAUD"]}, [{"action": "set_priority"}, {"action": "add_tag"}])
    r2 = _rule("r2", {"types": ["PAYMENT"]}, [{"action": "escalate"}])  # не матчит FRAUD
    calls: list[tuple[uuid.UUID, str]] = []

    async def apply(
        session: Any, ticket: Any, action: Any, *, rule_id: uuid.UUID, trigger: str
    ) -> bool:
        calls.append((rule_id, action["action"]))
        return True

    _patch(monkeypatch, [r1, r2], apply)
    session = _FakeSession()
    await _run(session, _ticket(type="FRAUD"), "on_create")

    assert [c[1] for c in calls] == ["set_priority", "add_tag"]  # только r1, в порядке
    assert all(c[0] == r1.id for c in calls)
    assert all(sp.committed for sp in session.savepoints)


async def test_failing_action_rolls_back_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = _rule("r", {}, [{"action": "a1"}, {"action": "a2"}])  # catch-all
    outcome = {"a1": False, "a2": True}

    async def apply(
        session: Any, ticket: Any, action: Any, *, rule_id: uuid.UUID, trigger: str
    ) -> bool:
        return outcome[action["action"]]

    _patch(monkeypatch, [rule], apply)
    session = _FakeSession()
    await _run(session, _ticket(), "on_create")

    assert session.savepoints[0].rolledback and not session.savepoints[0].committed
    assert session.savepoints[1].committed
    assert session.refreshed  # refresh после rollback сбойного действия (восстановление)


async def test_orchestration_load_error_not_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomRepo:
        async def list_active(self, trigger: str) -> list[AutomationRule]:
            raise RuntimeError("db down")

    monkeypatch.setattr(engine, "AutomationRuleRepository", lambda session: _BoomRepo())
    # Не пробрасывает (Реш.4).
    await _run(_FakeSession(), _ticket(), "on_create")


async def test_savepoint_commit_failure_not_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = _rule("r", {}, [{"action": "a"}])

    async def apply(
        session: Any, ticket: Any, action: Any, *, rule_id: uuid.UUID, trigger: str
    ) -> bool:
        return True

    _patch(monkeypatch, [rule], apply)
    session = _FakeSession(lambda: _FakeSavepoint(fail_commit=True))
    await _run(session, _ticket(), "on_create")  # не пробрасывает
    assert session.savepoints[0].rolledback  # recovery откатил savepoint


async def test_empty_rules_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []

    async def apply(*a: Any, **k: Any) -> bool:
        called.append(1)
        return True

    _patch(monkeypatch, [], apply)
    session = _FakeSession()
    await _run(session, _ticket(), "on_create")
    assert called == [] and session.savepoints == []


async def test_chain_of_actions_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = _rule("r", {}, [{"action": "set_priority"}, {"action": "add_tag"}, {"action": "notify"}])
    seen: list[str] = []

    async def apply(
        session: Any, ticket: Any, action: Any, *, rule_id: uuid.UUID, trigger: str
    ) -> bool:
        seen.append(action["action"])
        return True

    _patch(monkeypatch, [rule], apply)
    await _run(_FakeSession(), _ticket(), "on_create")
    assert seen == ["set_priority", "add_tag", "notify"]  # вся цепочка, в порядке
