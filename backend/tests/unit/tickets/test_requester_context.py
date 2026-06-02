"""Unit-тесты сборки контекста заявителя (enabler #81 для E3-5). FR-2.2, AT-003.

Платформенный клиент тут фейковый (Protocol `PlatformClient`) — сеть/Redis не нужны.
Проверяем: happy path, частичную деградацию по секциям, gate (клиент None), запрос
ТОЛЬКО по непустым id, и фабрику-зависимость `get_platform_client` (gate по токену).
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from api.clients.platform import (
    Booking,
    Collaborator,
    Contact,
    Premises,
    UserProfile,
)
from api.tickets.requester_context import (
    assemble_requester_context,
    get_platform_client,
)


def _user(uid: uuid.UUID) -> UserProfile:
    return UserProfile(
        id=uid,
        display_name="Иван Заявитель",
        email="ivan@example.com",
        phone="+70000000000",
        role="tenant",
        is_active=True,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )


def _premises(pid: uuid.UUID) -> Premises:
    return Premises(id=pid, address="СПб, Невский 1", kind="apartment", rooms=2, area_m2=54.0,
                    landlord_id=uuid.uuid4())


def _booking(bid: uuid.UUID, pid: uuid.UUID) -> Booking:
    return Booking(
        id=bid, premises_id=pid, tenant_id=uuid.uuid4(), landlord_id=uuid.uuid4(),
        status="active", period_start=datetime.date(2026, 1, 1), period_end=None,
        monthly_rent=50000.0,
    )


def _collaborator(cid: uuid.UUID) -> Collaborator:
    return Collaborator(
        id=cid, name="Клининг сервис", category="cleaning",
        contact=Contact(email="clean@example.com", phone=None), is_active=True,
    )


class FakePlatformClient:
    """Конфигурируемый фейк `PlatformClient`. Считает вызовы, чтобы проверить, что
    по отсутствующим id запросов нет."""

    def __init__(
        self,
        *,
        user: UserProfile | None = None,
        premises: Premises | None = None,
        booking: Booking | None = None,
        collaborator: Collaborator | None = None,
    ) -> None:
        self._user = user
        self._premises = premises
        self._booking = booking
        self._collaborator = collaborator
        self.calls: list[str] = []

    async def get_user(self, user_id: uuid.UUID) -> UserProfile | None:
        self.calls.append("user")
        return self._user

    async def get_premises(self, premises_id: uuid.UUID) -> Premises | None:
        self.calls.append("premises")
        return self._premises

    async def get_booking(self, booking_id: uuid.UUID) -> Booking | None:
        self.calls.append("booking")
        return self._booking

    async def get_collaborator(self, collaborator_id: uuid.UUID) -> Collaborator | None:
        self.calls.append("collaborator")
        return self._collaborator


class _Ticket:
    """Лёгкий стенд заявки (только id-поля, нужные сборке)."""

    def __init__(
        self,
        *,
        requester_id: uuid.UUID,
        premises_id: uuid.UUID | None = None,
        booking_id: uuid.UUID | None = None,
        collaborator_id: uuid.UUID | None = None,
    ) -> None:
        self.requester_id = requester_id
        self.premises_id = premises_id
        self.booking_id = booking_id
        self.collaborator_id = collaborator_id


async def test_all_sections_populated() -> None:
    rid, pid, bid, cid = (uuid.uuid4() for _ in range(4))
    client = FakePlatformClient(
        user=_user(rid), premises=_premises(pid), booking=_booking(bid, pid),
        collaborator=_collaborator(cid),
    )
    ticket = _Ticket(requester_id=rid, premises_id=pid, booking_id=bid, collaborator_id=cid)

    ctx = await assemble_requester_context(ticket, client)  # type: ignore[arg-type]

    assert ctx.degraded is False
    assert ctx.user is not None and ctx.user.id == rid
    assert ctx.premises is not None and ctx.booking is not None and ctx.collaborator is not None
    assert set(client.calls) == {"user", "premises", "booking", "collaborator"}


async def test_only_non_empty_ids_are_fetched() -> None:
    """Заявка без premises/booking/collaborator — запрос только за user."""
    rid = uuid.uuid4()
    client = FakePlatformClient(user=_user(rid))
    ticket = _Ticket(requester_id=rid)

    ctx = await assemble_requester_context(ticket, client)  # type: ignore[arg-type]

    assert ctx.degraded is False
    assert ctx.user is not None
    assert ctx.premises is None and ctx.booking is None and ctx.collaborator is None
    assert client.calls == ["user"]  # за отсутствующими id не ходим


async def test_partial_degradation_one_section_none() -> None:
    """Сосед вернул None по premises (недоступен/404) — остальные секции живы."""
    rid, pid = uuid.uuid4(), uuid.uuid4()
    client = FakePlatformClient(user=_user(rid), premises=None)  # premises деградировал
    ticket = _Ticket(requester_id=rid, premises_id=pid)

    ctx = await assemble_requester_context(ticket, client)  # type: ignore[arg-type]

    assert ctx.degraded is False  # degraded — про gate, не про отсутствие сущности
    assert ctx.user is not None
    assert ctx.premises is None


async def test_gate_off_when_client_none() -> None:
    """Интеграция выключена (клиент None) → degraded=True, все секции None, без вызовов."""
    ticket = _Ticket(requester_id=uuid.uuid4(), premises_id=uuid.uuid4())

    ctx = await assemble_requester_context(ticket, None)  # type: ignore[arg-type]

    assert ctx.degraded is True
    assert ctx.user is None and ctx.premises is None
    assert ctx.booking is None and ctx.collaborator is None


async def test_get_platform_client_gated_off_on_empty_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой platform_api_token → зависимость отдаёт None (интеграция выключена)."""
    import api.tickets.requester_context as rc

    class _S:
        platform_api_token = ""
        platform_api_base_url = "http://platform"
        platform_cache_ttl_seconds = 300
        client_timeout_seconds = 5.0
        client_breaker_failure_threshold = 5
        client_breaker_reset_timeout = 30.0
        client_retry_attempts = 3
        client_retry_base_delay = 0.1
        client_retry_max_delay = 2.0

    monkeypatch.setattr(rc, "get_settings", lambda: _S())
    gen = get_platform_client()
    client = await gen.__anext__()
    assert client is None
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


async def test_get_platform_client_builds_client_when_token_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Непустой токен → зависимость строит HttpPlatformClient (dev/test путь, см. #77)."""
    import api.tickets.requester_context as rc
    from api.clients.platform import HttpPlatformClient

    class _S:
        platform_api_token = "dev-token"  # noqa: S105 — тестовый плейсхолдер
        platform_api_base_url = "http://platform"
        platform_cache_ttl_seconds = 300
        client_timeout_seconds = 5.0
        client_breaker_failure_threshold = 5
        client_breaker_reset_timeout = 30.0
        client_retry_attempts = 3
        client_retry_base_delay = 0.1
        client_retry_max_delay = 2.0

    monkeypatch.setattr(rc, "get_settings", lambda: _S())
    gen = get_platform_client()
    client = await gen.__anext__()
    assert isinstance(client, HttpPlatformClient)
    # Закрыть генератор (httpx.AsyncClient освобождается в finally async with).
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
