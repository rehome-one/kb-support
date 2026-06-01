"""HTTP-реализация platform-клиента (E3-3, #71) поверх фундамента #70.

Провизорный контракт rehome.one platform API (ADR-0006 Решение 2) изолирован
ЗДЕСЬ: функции `_map_*` мапят провизорный JSON → доменные DTO. Смена upstream =
правка только этих мапперов + ADR-0006 (Решение 1/4).

Деградация (AT-003): недоступность соседа (`ExternalServiceError`/`CircuitOpenError`),
404/4xx и битый JSON → `None` с WARN-логом (не тихое проглатывание). В лог НЕ
попадает тело ответа (ФЗ-152) — только operation/status (id — в пути, не ПДн).
Кешируется ТОЛЬКО успешный 200 (не 404/None); ключ с namespace типа сущности.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from api.clients.base import ResilientHttpClient
from api.clients.cache import Cache
from api.clients.errors import ExternalServiceError
from api.clients.platform.auth import TokenProvider
from api.clients.platform.models import Booking, Collaborator, Contact, Premises, UserProfile
from api.observability.logging import get_logger

_logger = get_logger("clients.platform")

T = TypeVar("T")


def _opt_uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _opt_dt(value: Any) -> datetime.datetime | None:
    return datetime.datetime.fromisoformat(value) if value else None


# --- Мапперы провизорного JSON → доменные DTO. provisional contract, see ADR-0006. ---


def _map_user(d: dict[str, Any]) -> UserProfile:  # provisional contract, see ADR-0006
    return UserProfile(
        id=uuid.UUID(d["id"]),
        display_name=d["display_name"],
        email=d.get("email"),
        phone=d.get("phone"),
        role=d["role"],
        is_active=d["is_active"],
        created_at=_opt_dt(d.get("created_at")),
    )


def _map_premises(d: dict[str, Any]) -> Premises:  # provisional contract, see ADR-0006
    return Premises(
        id=uuid.UUID(d["id"]),
        address=d["address"],
        kind=d["kind"],
        rooms=d.get("rooms"),
        area_m2=d.get("area_m2"),
        landlord_id=_opt_uuid(d.get("landlord_id")),
    )


def _map_booking(d: dict[str, Any]) -> Booking:  # provisional contract, see ADR-0006
    return Booking(
        id=uuid.UUID(d["id"]),
        premises_id=uuid.UUID(d["premises_id"]),
        tenant_id=uuid.UUID(d["tenant_id"]),
        landlord_id=uuid.UUID(d["landlord_id"]),
        status=d["status"],
        period_start=datetime.date.fromisoformat(d["period_start"]),
        period_end=datetime.date.fromisoformat(d["period_end"]) if d.get("period_end") else None,
        monthly_rent=d.get("monthly_rent"),
    )


def _map_collaborator(d: dict[str, Any]) -> Collaborator:  # provisional contract, see ADR-0006
    contact_raw = d.get("contact")
    contact = (
        Contact(email=contact_raw.get("email"), phone=contact_raw.get("phone"))
        if contact_raw
        else None
    )
    return Collaborator(
        id=uuid.UUID(d["id"]),
        name=d["name"],
        category=d["category"],
        contact=contact,
        is_active=d["is_active"],
    )


class HttpPlatformClient:
    """`PlatformClient` поверх `ResilientHttpClient` (#70) + `Cache`.

    Зависимости инъектируются явно (тесты — без сети/Redis). НЕ создаёт app-level
    синглтон со `StaticTokenProvider` (см. auth.py / #77) — боевой путь подставит
    реальный провайдер позже (#73)."""

    def __init__(
        self,
        *,
        http_client: ResilientHttpClient,
        token_provider: TokenProvider,
        cache: Cache,
        cache_ttl_seconds: int,
    ) -> None:
        self._http = http_client
        self._token_provider = token_provider
        self._cache = cache
        self._ttl = cache_ttl_seconds

    async def get_user(self, user_id: uuid.UUID) -> UserProfile | None:
        return await self._get(
            f"/api/v1/users/{user_id}", "get_user", f"platform:user:{user_id}", _map_user
        )

    async def get_premises(self, premises_id: uuid.UUID) -> Premises | None:
        return await self._get(
            f"/api/v1/premises/{premises_id}",
            "get_premises",
            f"platform:premises:{premises_id}",
            _map_premises,
        )

    async def get_booking(self, booking_id: uuid.UUID) -> Booking | None:
        return await self._get(
            f"/api/v1/bookings/{booking_id}",
            "get_booking",
            f"platform:booking:{booking_id}",
            _map_booking,
        )

    async def get_collaborator(self, collaborator_id: uuid.UUID) -> Collaborator | None:
        return await self._get(
            f"/api/v1/collaborators/{collaborator_id}",
            "get_collaborator",
            f"platform:collaborator:{collaborator_id}",
            _map_collaborator,
        )

    async def _get(
        self, path: str, operation: str, cache_key: str, mapper: Callable[[dict[str, Any]], T]
    ) -> T | None:
        data = await self._fetch(path, operation, cache_key)
        if data is None:
            return None
        try:
            return mapper(data)
        except (KeyError, TypeError, ValueError):
            # Неполный/невалидный 200-JSON (провизорный контракт разошёлся) — деградируем.
            _logger.warning("platform %s degraded: mapping failed", operation)
            return None

    async def _fetch(self, path: str, operation: str, cache_key: str) -> dict[str, Any] | None:
        """Cache-aside GET через ResilientHttpClient. Кешируется только 200.

        Использует `request` (не `get_json`): нужно инспектировать статус, чтобы
        отличить 200 от 404/4xx, и не звать `.json()` на не-JSON теле ошибки."""
        cached = await self._cache.get(cache_key)
        if cached is not None:
            parsed: dict[str, Any] = json.loads(cached)
            return parsed

        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await self._http.request("GET", path, operation=operation, headers=headers)
        except ExternalServiceError as exc:
            # Включает CircuitOpenError. Тело ответа не утекает (инвариант #70).
            _logger.warning("platform %s degraded: %s", operation, type(exc).__name__)
            return None

        if response.status_code >= 400:
            _logger.warning("platform %s degraded: status=%d", operation, response.status_code)
            return None

        try:
            payload: dict[str, Any] = response.json()
        except (ValueError, json.JSONDecodeError):
            _logger.warning("platform %s degraded: malformed JSON", operation)
            return None

        await self._cache.set(cache_key, json.dumps(payload), self._ttl)
        return payload
