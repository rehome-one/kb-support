"""Unit-тесты зависимости get_current_principal (конфигурация/токен)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from api.auth import dependencies as deps
from api.auth.dependencies import _verifier, build_verifier, get_current_principal
from api.auth.jwks import JwksCache
from api.auth.jwt_verifier import JwtVerifier
from api.auth.principal import PrincipalKind
from api.config import Settings, get_settings
from api.errors import ProblemException
from api.observability.context import actor_sub_var, get_actor_sub
from tests.unit.auth.conftest import AUDIENCE, ISSUER, TokenMaker


def _reset_caches() -> None:
    get_settings.cache_clear()
    _verifier.cache_clear()


def test_build_verifier_none_when_unconfigured() -> None:
    assert build_verifier(Settings(auth_jwks_url="")) is None


def test_build_verifier_present_when_configured() -> None:
    assert build_verifier(Settings(auth_jwks_url="https://kc.local/jwks")) is not None


def test_not_configured_returns_401() -> None:
    _reset_caches()
    try:
        with pytest.raises(ProblemException) as exc:
            asyncio.run(get_current_principal(credentials=None))
        assert exc.value.status == 401
        assert "not configured" in (exc.value.detail or "")
    finally:
        _reset_caches()


def test_missing_bearer_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KBS_AUTH_JWKS_URL", "https://kc.local/jwks")
    _reset_caches()
    try:
        with pytest.raises(ProblemException) as exc:
            asyncio.run(get_current_principal(credentials=None))
        assert exc.value.status == 401
        assert "Missing" in (exc.value.detail or "")
    finally:
        _reset_caches()


@pytest.mark.asyncio
async def test_valid_credentials_return_principal_and_bind_actor(
    monkeypatch: pytest.MonkeyPatch,
    stub_fetcher: Callable[[str], Awaitable[dict[str, Any]]],
    make_token: TokenMaker,
) -> None:
    verifier = JwtVerifier(
        jwks=JwksCache("u", ttl_seconds=300, fetcher=stub_fetcher),
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=["RS256"],
        leeway=0,
    )
    monkeypatch.setattr(deps, "_verifier", lambda: verifier)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=make_token({"kbs_kind": "operator"})
    )
    token = actor_sub_var.set(None)
    try:
        # await (не asyncio.run) — тот же контекст, виден bind_actor_sub.
        principal = await get_current_principal(credentials=credentials)
        assert principal.kind is PrincipalKind.OPERATOR
        assert get_actor_sub() == str(principal.user_id)  # actor_sub привязан к логам
    finally:
        actor_sub_var.reset(token)
