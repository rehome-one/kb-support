"""Тесты platform-клиента (E3-3, #71): маппинг провизорного JSON → DTO,
graceful degradation, кеш, auth-заголовок. httpx.MockTransport + InMemoryCache;
clock/sleep инжектируются (детерминизм, без сети/Redis)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from unittest import mock

import httpx

from api.clients.base import ResilientHttpClient
from api.clients.cache import InMemoryCache
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.platform import adapter as adapter_module
from api.clients.platform.adapter import HttpPlatformClient
from api.clients.platform.auth import StaticTokenProvider
from api.clients.platform.models import Booking, Collaborator, Premises, UserProfile
from api.clients.retry import RetryPolicy

USER_ID = uuid.uuid4()
PREMISES_ID = uuid.uuid4()
BOOKING_ID = uuid.uuid4()
COLLAB_ID = uuid.uuid4()
LANDLORD_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    attempts: int = 2,
    threshold: int = 5,
    ttl: int = 300,
    token: str = "test-token",
    clock: _Clock | None = None,
) -> tuple[HttpPlatformClient, InMemoryCache]:
    clock = clock or _Clock()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://platform")
    rc = ResilientHttpClient(
        client_name="platform",
        http=http,
        breaker=CircuitBreaker(failure_threshold=threshold, reset_timeout=30.0, now=clock),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    cache = InMemoryCache(now=clock)
    client = HttpPlatformClient(
        http_client=rc,
        token_provider=StaticTokenProvider(token),
        cache=cache,
        cache_ttl_seconds=ttl,
    )
    return client, cache


# --- happy-path: провизорный JSON → доменный DTO ---


async def test_get_user_maps_all_fields() -> None:
    body = {
        "id": str(USER_ID),
        "display_name": "Иван Петров",
        "email": "ivan@example.ru",
        "phone": "+79990001122",
        "role": "tenant",
        "is_active": True,
        "created_at": "2026-01-01T10:00:00+00:00",
    }
    client, _ = _make(lambda req: httpx.Response(200, json=body))
    user = await client.get_user(USER_ID)
    assert user == UserProfile(
        id=USER_ID,
        display_name="Иван Петров",
        email="ivan@example.ru",
        phone="+79990001122",
        role="tenant",
        is_active=True,
        created_at=user.created_at if user else None,
    )
    assert user is not None and user.created_at is not None


async def test_get_user_nullable_fields() -> None:
    body = {
        "id": str(USER_ID),
        "display_name": "NoContact",
        "email": None,
        "phone": None,
        "role": "agent",
        "is_active": False,
        "created_at": None,
    }
    client, _ = _make(lambda req: httpx.Response(200, json=body))
    user = await client.get_user(USER_ID)
    assert user is not None
    assert user.email is None and user.phone is None and user.created_at is None


async def test_get_premises_maps() -> None:
    body = {
        "id": str(PREMISES_ID),
        "address": "СПб, Невский 1",
        "kind": "flat",
        "rooms": 2,
        "area_m2": 54.3,
        "landlord_id": str(LANDLORD_ID),
    }
    client, _ = _make(lambda req: httpx.Response(200, json=body))
    p = await client.get_premises(PREMISES_ID)
    assert p == Premises(
        id=PREMISES_ID,
        address="СПб, Невский 1",
        kind="flat",
        rooms=2,
        area_m2=54.3,
        landlord_id=LANDLORD_ID,
    )


async def test_get_booking_maps() -> None:
    body = {
        "id": str(BOOKING_ID),
        "premises_id": str(PREMISES_ID),
        "tenant_id": str(TENANT_ID),
        "landlord_id": str(LANDLORD_ID),
        "status": "active",
        "period_start": "2026-01-01",
        "period_end": None,
        "monthly_rent": 45000,
    }
    client, _ = _make(lambda req: httpx.Response(200, json=body))
    b = await client.get_booking(BOOKING_ID)
    assert isinstance(b, Booking)
    assert b.premises_id == PREMISES_ID and b.period_end is None and b.monthly_rent == 45000


async def test_get_collaborator_with_contact() -> None:
    body = {
        "id": str(COLLAB_ID),
        "name": "Клининг СПб",
        "category": "cleaning",
        "contact": {"email": "c@cln.ru", "phone": None},
        "is_active": True,
    }
    client, _ = _make(lambda req: httpx.Response(200, json=body))
    c = await client.get_collaborator(COLLAB_ID)
    assert isinstance(c, Collaborator)
    assert c.contact is not None and c.contact.email == "c@cln.ru" and c.contact.phone is None


async def test_get_collaborator_null_contact() -> None:
    body = {
        "id": str(COLLAB_ID),
        "name": "X",
        "category": "other",
        "contact": None,
        "is_active": True,
    }
    client, _ = _make(lambda req: httpx.Response(200, json=body))
    c = await client.get_collaborator(COLLAB_ID)
    assert c is not None and c.contact is None


# --- auth ---


async def test_attaches_bearer_token() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "id": str(USER_ID),
                "display_name": "x",
                "email": None,
                "phone": None,
                "role": "tenant",
                "is_active": True,
                "created_at": None,
            },
        )

    client, _ = _make(handler, token="secret-m2m")
    await client.get_user(USER_ID)
    assert seen["auth"] == "Bearer secret-m2m"


# --- graceful degradation ---


async def test_404_returns_none_and_not_cached() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client, _ = _make(handler)
    assert await client.get_user(USER_ID) is None
    # 404 не кешируется — второй вызов снова идёт к соседу.
    assert await client.get_user(USER_ID) is None
    assert calls["n"] == 2


async def test_4xx_returns_none() -> None:
    client, _ = _make(lambda req: httpx.Response(403))
    assert await client.get_premises(PREMISES_ID) is None


async def test_5xx_degrades_to_none() -> None:
    client, _ = _make(lambda req: httpx.Response(503), attempts=2)
    assert await client.get_booking(BOOKING_ID) is None


async def test_transport_error_degrades_to_none() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client, _ = _make(handler, attempts=2)
    assert await client.get_user(USER_ID) is None


async def test_circuit_open_degrades_to_none() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    client, _ = _make(handler, attempts=1, threshold=1)
    assert await client.get_user(USER_ID) is None  # открывает breaker
    assert await client.get_user(USER_ID) is None  # circuit-open → None без вызова
    assert calls["n"] == 1


async def test_malformed_json_degrades_to_none() -> None:
    client, _ = _make(lambda req: httpx.Response(200, text="not-json"))
    assert await client.get_user(USER_ID) is None


async def test_incomplete_json_mapping_fails_to_none() -> None:
    # Валидный JSON, но без обязательного поля role → маппинг падает → None.
    body = {"id": str(USER_ID), "display_name": "x", "is_active": True}
    client, _ = _make(lambda req: httpx.Response(200, json=body))
    assert await client.get_user(USER_ID) is None


# --- cache ---


async def test_cache_hit_skips_network() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "id": str(USER_ID),
                "display_name": "x",
                "email": None,
                "phone": None,
                "role": "tenant",
                "is_active": True,
                "created_at": None,
            },
        )

    client, _ = _make(handler)
    await client.get_user(USER_ID)
    await client.get_user(USER_ID)
    assert calls["n"] == 1  # второй — из кеша


async def test_cache_expires_refetches() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "id": str(USER_ID),
                "display_name": "x",
                "email": None,
                "phone": None,
                "role": "tenant",
                "is_active": True,
                "created_at": None,
            },
        )

    clock = _Clock()
    client, _ = _make(handler, ttl=100, clock=clock)
    await client.get_user(USER_ID)
    clock.t = 100.0  # TTL истёк
    await client.get_user(USER_ID)
    assert calls["n"] == 2


# --- ФЗ-152: тело ответа (ПДн) не попадает в логи ---


async def test_pii_not_logged_on_degradation() -> None:
    body = {
        "id": str(USER_ID),
        "display_name": "Секретное Имя",
        "email": "secret@pii.ru",
        "phone": "+79991234567",
        # role отсутствует → маппинг падает (200 с ПДн в теле)
        "is_active": True,
    }
    # Перехватываем сам вызов logger.warning (независимо от глобального уровня
    # логирования / logging.disable в других тестах): проверяем, что ПДн не
    # передаются в логгер ни в шаблоне, ни в аргументах.
    with mock.patch.object(adapter_module._logger, "warning") as warn:
        client, _ = _make(lambda req: httpx.Response(200, json=body))
        assert await client.get_user(USER_ID) is None

    assert warn.called, "ожидался WARN о деградации"
    logged = " ".join(str(arg) for call in warn.call_args_list for arg in call.args)
    assert "secret@pii.ru" not in logged
    assert "+79991234567" not in logged
    assert "Секретное Имя" not in logged
