"""Integration-тесты inbound гарантийного исключения (E10-10 PR-A #200) — требуют Postgres.

Покрывают: m2m-only (не-SERVICE→403); fail-closed (пустой секрет→403); невалидная подпись→403;
валидный → системное создание GUARANTEE (type/channel=SYSTEM/case_state=CLAIM_SUBMITTED + регресс-
ссылки); идемпотентность по reference (повтор→одна заявка). Подпись считается над raw-телом.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.webhooks.signing import compute_signature

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Inbound guarantee требует живой Postgres (CI / POSTGRES_AVAILABLE=1).",
)

_SECRET = "test-guarantee-inbound-secret-1234"
_URL = "/api/v1/support/guarantee-events"
_SERVICE = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.SERVICE)
_OPERATOR = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR)


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture(autouse=True)
def _override_db_session() -> Iterator[None]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_test_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _get_test_session
    yield
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_principal, None)
    asyncio.run(engine.dispose())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _enable_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    replacement = get_settings().model_copy(update={"guarantee_inbound_secret": _SECRET})
    monkeypatch.setattr("api.webhooks.guarantee_inbound.get_settings", lambda: replacement)


def _signed(body: dict[str, object]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    ts = int(datetime.datetime.now(datetime.UTC).timestamp())
    sig = f"t={ts},v1={compute_signature(payload=raw, secret=_SECRET, timestamp=ts)}"
    return raw, {"Content-Type": "application/json", "X-Signature": sig}


def _payload(reference: str, **extra: object) -> dict[str, object]:
    return {"exception_kind": "guarantee_suspended", "reference": reference, **extra}


def _post(client: TestClient, body: dict[str, object]) -> Response:
    raw, headers = _signed(body)
    return client.post(_URL, content=raw, headers=headers)


def _count_by_reference(reference: str) -> int:
    async def _inner() -> int:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM tickets WHERE type='GUARANTEE' "
                            "AND custom_fields->>'guarantee_reference' = :ref"
                        ),
                        {"ref": reference},
                    )
                ).first()
                return int(row[0]) if row else 0
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_non_service_forbidden(client: TestClient) -> None:
    _use(_OPERATOR)
    assert _post(client, _payload("ref-1")).status_code == 403


def test_secret_off_fail_closed(client: TestClient) -> None:
    # Дефолтный guarantee_inbound_secret пуст → fail-closed даже от SERVICE.
    _use(_SERVICE)
    assert _post(client, _payload("ref-2")).status_code == 403


def test_invalid_signature_forbidden(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_secret(monkeypatch)
    _use(_SERVICE)
    body = json.dumps(_payload("ref-3")).encode()
    resp = client.post(
        _URL,
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": "t=1,v1=bad"},
    )
    assert resp.status_code == 403


def test_valid_creates_guarantee_with_regress_refs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_secret(monkeypatch)
    _use(_SERVICE)
    reference = f"ref-{uuid.uuid4().hex}"
    regress_id = str(uuid.uuid4())
    resp = _post(
        client,
        _payload(
            reference,
            regress_obligation_id=regress_id,
            missed_payment_id=str(uuid.uuid4()),
            late_fee_accrued=1500.50,
        ),
    )
    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    assert data["type"] == "GUARANTEE"
    assert data["channel"] == "SYSTEM"
    assert data["case_state"] == "CLAIM_SUBMITTED"
    assert data["regress_obligation_id"] == regress_id  # плоская колонка-ссылка
    assert _count_by_reference(reference) == 1


def test_idempotent_by_reference(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_secret(monkeypatch)
    _use(_SERVICE)
    reference = f"ref-{uuid.uuid4().hex}"
    first = _post(client, _payload(reference))
    assert first.status_code == 202
    second = _post(client, _payload(reference))
    assert second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]  # та же заявка
    assert _count_by_reference(reference) == 1  # повтор не двоит
