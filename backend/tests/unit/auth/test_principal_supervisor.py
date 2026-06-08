"""Unit-тесты scope супервайзера (E8-2, #166): аддитивность (ADR-0011 Решение 1)."""

from __future__ import annotations

import uuid

from api.auth.principal import Principal, PrincipalKind
from api.auth.scopes import STAFF_SUPERVISOR_SCOPE, STAFF_SUPPORT_SCOPE


def _operator(*scopes: str) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, scopes=frozenset(scopes))


def test_supervisor_scope_grants_is_staff_supervisor() -> None:
    assert _operator(STAFF_SUPERVISOR_SCOPE).is_staff_supervisor is True


def test_no_scope_is_not_supervisor() -> None:
    assert _operator().is_staff_supervisor is False
    assert _operator(STAFF_SUPPORT_SCOPE).is_staff_supervisor is False


def test_supervisor_does_not_imply_support_additivity() -> None:
    # Аддитивно: supervisor БЕЗ staff_support не получает прав оператора шаблонов.
    supervisor_only = _operator(STAFF_SUPERVISOR_SCOPE)
    assert supervisor_only.is_staff_supervisor is True
    assert supervisor_only.is_staff_support is False


def test_support_does_not_imply_supervisor() -> None:
    assert _operator(STAFF_SUPPORT_SCOPE).is_staff_supervisor is False


def test_both_scopes_grant_both() -> None:
    both = _operator(STAFF_SUPPORT_SCOPE, STAFF_SUPERVISOR_SCOPE)
    assert both.is_staff_support is True
    assert both.is_staff_supervisor is True
