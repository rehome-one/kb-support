"""Фикстуры контрактных тестов (#4).

Источник истины — `docs/openapi.yaml` (production, #11). Контракт проверяется
двумя способами:
- `assert_response_conforms` — валидация РЕАЛЬНОГО ответа приложения против схемы
  ответа операции (jsonschema; OpenAPI 3.1 = JSON Schema 2020-12). Ловит дрейф
  «код ≠ контракт».
- `prism_mock` — опциональный Prism mock-сервер из той же спеки (env-gated).
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.auth.scopes import STAFF_ADMIN_SCOPE, STAFF_SUPPORT_SCOPE
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketTeam

SPEC_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.yaml"
SPEC: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))

_BASE_URI = "urn:kb-support:openapi"
_REGISTRY = Registry().with_resource(
    _BASE_URI, Resource.from_contents(SPEC, default_specification=DRAFT202012)
)

requires_postgres = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason="Контрактные тесты против реального приложения требуют Postgres (CI/POSTGRES_AVAILABLE)",
)


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def assert_response_conforms(path: str, method: str, status: str, body: object) -> None:
    """Проверить, что `body` соответствует схеме ответа операции из docs/openapi.yaml."""
    ref = (
        f"{_BASE_URI}#/paths/{_escape_pointer(path)}/{method}"
        f"/responses/{status}/content/{_escape_pointer('application/json')}/schema"
    )
    Draft202012Validator({"$ref": ref}, registry=_REGISTRY).validate(body)


@contextmanager
def _testclient_with(principal: Principal) -> Iterator[TestClient]:
    """TestClient с инжектированным принципалом и NullPool-сессией к тестовой БД.

    NullPool открывает свежее соединение на текущем event loop (глобальный
    QueuePool кешировал бы соединение первого loop → cross-loop ошибки)."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session() -> Any:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture
def operator_client() -> Iterator[TestClient]:
    """TestClient с инжектированным оператором (без admin-скоупа)."""
    # Стабильный оператор на время фикстуры: POST и GET должны идти от ОДНОГО
    # субъекта, иначе созданная заявка не видна в списке (он владелец).
    operator = Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        teams=frozenset({TicketTeam.SUPPORT}),
    )
    with _testclient_with(operator) as client:
        yield client


@pytest.fixture
def service_client() -> Iterator[TestClient]:
    """TestClient с m2m (SERVICE) принципалом — для /from-chat (E3-1, #69)."""
    with _testclient_with(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.SERVICE)) as client:
        yield client


@pytest.fixture
def admin_client() -> Iterator[TestClient]:
    """TestClient с админ-принципалом (оператор + `staff_admin`) — для SLA-конфигурации (#86)."""
    admin = Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        scopes=frozenset({STAFF_ADMIN_SCOPE}),
        teams=frozenset({TicketTeam.SUPPORT}),
    )
    with _testclient_with(admin) as client:
        yield client


@pytest.fixture
def support_client() -> Iterator[TestClient]:
    """TestClient с принципалом поддержки (оператор + `staff_support`) — CRUD шаблонов (#126)."""
    support = Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        scopes=frozenset({STAFF_SUPPORT_SCOPE}),
        teams=frozenset({TicketTeam.SUPPORT}),
    )
    with _testclient_with(support) as client:
        yield client


@pytest.fixture
def prism_mock() -> Iterator[str]:
    """Prism mock-сервер из docs/openapi.yaml (env-gated `RUN_PRISM_CONTRACT=1`).

    npx-fetch prism медленный/флапающий — поэтому по умолчанию скип. Локально:
    `RUN_PRISM_CONTRACT=1 pytest tests/contract/`.
    """
    if "RUN_PRISM_CONTRACT" not in os.environ:
        pytest.skip("Prism mock отключён (выставьте RUN_PRISM_CONTRACT=1).")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    process = subprocess.Popen(
        [
            "npx",
            "-y",
            "@stoplight/prism-cli@latest",
            "mock",
            str(SPEC_PATH),
            "-p",
            str(port),
            "-h",
            "127.0.0.1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            with socket.socket() as check:
                if check.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(1)
        else:
            pytest.skip("Prism не стартовал за отведённое время.")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=10)
