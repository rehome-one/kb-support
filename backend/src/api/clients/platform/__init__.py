"""Platform-клиент контекста заявителя (E3-3, #71).

Публичная поверхность: `PlatformClient` Protocol + доменные DTO + HTTP-реализация
`HttpPlatformClient` + `TokenProvider`. Провизорный контракт rehome.one platform
(ADR-0006) изолирован в `adapter.py`. Связь — только по HTTP (арх-константа)."""

from __future__ import annotations

from api.clients.auth import StaticTokenProvider, TokenProvider
from api.clients.platform.adapter import HttpPlatformClient
from api.clients.platform.models import (
    Booking,
    Collaborator,
    Contact,
    Premises,
    UserProfile,
)
from api.clients.platform.protocol import PlatformClient

__all__ = [
    "PlatformClient",
    "HttpPlatformClient",
    "TokenProvider",
    "StaticTokenProvider",
    "UserProfile",
    "Premises",
    "Booking",
    "Collaborator",
    "Contact",
]
