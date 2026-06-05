"""Unit-тесты best-effort учёта usage_count (E6-4 #128) — без БД.

Покрывают SAVEPOINT-изоляцию: found → commit; not-found → commit (no-op) без ошибки;
сбой инкремента → rollback savepoint, не пробрасывается (отправка сообщения не падает).
"""

from __future__ import annotations

import uuid

import pytest

from api.canned import usage


class _FakeSavepoint:
    def __init__(self) -> None:
        self.committed = False
        self.rolledback = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolledback = True


class _FakeSession:
    def __init__(self) -> None:
        self.savepoint = _FakeSavepoint()

    async def begin_nested(self) -> _FakeSavepoint:
        return self.savepoint


class _FakeRepo:
    def __init__(self, *, result: bool | None, boom: bool = False) -> None:
        self._result = result
        self._boom = boom

    async def increment_usage(self, canned_id: uuid.UUID) -> bool:
        if self._boom:
            raise RuntimeError("db error")
        assert self._result is not None
        return self._result


def _patch_repo(monkeypatch: pytest.MonkeyPatch, repo: _FakeRepo) -> None:
    monkeypatch.setattr(usage, "CannedResponseRepository", lambda session: repo)


async def test_found_commits_savepoint(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    _patch_repo(monkeypatch, _FakeRepo(result=True))
    await usage.record_canned_usage(session, uuid.uuid4())  # type: ignore[arg-type]
    assert session.savepoint.committed is True
    assert session.savepoint.rolledback is False


async def test_not_found_commits_without_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    _patch_repo(monkeypatch, _FakeRepo(result=False))
    await usage.record_canned_usage(session, uuid.uuid4())  # type: ignore[arg-type]
    assert session.savepoint.committed is True  # no-op коммит, без исключения


async def test_increment_failure_rolls_back_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    _patch_repo(monkeypatch, _FakeRepo(result=None, boom=True))
    # Не пробрасывает (best-effort) — отправка сообщения не падает.
    await usage.record_canned_usage(session, uuid.uuid4())  # type: ignore[arg-type]
    assert session.savepoint.rolledback is True
    assert session.savepoint.committed is False
