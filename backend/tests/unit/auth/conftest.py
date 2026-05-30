"""Фикстуры контрактных тестов auth: тестовый RSA-ключ + стаб JWKS (оффлайн)."""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

KID = "test-key-1"
ISSUER = "https://keycloak.local/realms/rehome"
AUDIENCE = "kb-support"


def _to_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _public_jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return jwk


# Один ключ на сессию (генерация RSA ~раз). Второй — для теста чужой подписи.
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _to_pem(_PRIVATE)
_OTHER_PEM = _to_pem(_OTHER_PRIVATE)
_JWKS: dict[str, Any] = {"keys": [_public_jwk(_PRIVATE, KID)]}


@pytest.fixture
def jwks_dict() -> dict[str, Any]:
    return _JWKS


@pytest.fixture
def other_private_pem() -> str:
    return _OTHER_PEM


TokenMaker = Callable[..., str]


@pytest.fixture
def make_token() -> TokenMaker:
    def _make(
        claims: dict[str, Any] | None = None,
        *,
        kid: str | None = KID,
        key: str = _PRIVATE_PEM,
        exp_delta: int = 300,
    ) -> str:
        now = datetime.datetime.now(datetime.UTC)
        payload: dict[str, Any] = {
            "sub": str(uuid.uuid4()),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + datetime.timedelta(seconds=exp_delta),
        }
        if claims:
            payload.update(claims)
        headers = {"kid": kid} if kid is not None else {}
        return jwt.encode(payload, key, algorithm="RS256", headers=headers)

    return _make


@pytest.fixture
def stub_fetcher(jwks_dict: dict[str, Any]) -> Callable[[str], Awaitable[dict[str, Any]]]:
    async def _fetch(url: str) -> dict[str, Any]:
        return jwks_dict

    return _fetch
