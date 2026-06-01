"""Доменные DTO контекста заявителя (E3-3, #71).

Это НАШИ модели, независимые от провизорной формы rehome.one platform API.
Маппинг провизорный JSON → эти DTO живёт в `adapter.py` (ADR-0006 Решение 1):
смена upstream-контракта правит только адаптер, не эти типы и не потребителя (#73).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class UserProfile:
    id: uuid.UUID
    display_name: str
    email: str | None
    phone: str | None
    role: str
    is_active: bool
    created_at: datetime.datetime | None


@dataclass(frozen=True)
class Premises:
    id: uuid.UUID
    address: str
    kind: str
    rooms: int | None
    area_m2: float | None
    landlord_id: uuid.UUID | None


@dataclass(frozen=True)
class Booking:
    id: uuid.UUID
    premises_id: uuid.UUID
    tenant_id: uuid.UUID
    landlord_id: uuid.UUID
    status: str
    period_start: datetime.date
    period_end: datetime.date | None
    monthly_rent: float | None


@dataclass(frozen=True)
class Contact:
    email: str | None
    phone: str | None


@dataclass(frozen=True)
class Collaborator:
    id: uuid.UUID
    name: str
    category: str
    contact: Contact | None
    is_active: bool
