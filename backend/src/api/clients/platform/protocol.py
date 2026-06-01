"""Интерфейс platform-клиента контекста заявителя (E3-3, #71).

Потребитель (#73 RequesterContext) зависит от этого Protocol и доменных DTO,
не от HTTP-реализации/провизорной формы. Любой метод возвращает `None` при
недоступности соседа или отсутствии сущности (graceful degradation, AT-003)."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from api.clients.platform.models import Booking, Collaborator, Premises, UserProfile


@runtime_checkable
class PlatformClient(Protocol):
    async def get_user(self, user_id: uuid.UUID) -> UserProfile | None: ...
    async def get_premises(self, premises_id: uuid.UUID) -> Premises | None: ...
    async def get_booking(self, booking_id: uuid.UUID) -> Booking | None: ...
    async def get_collaborator(self, collaborator_id: uuid.UUID) -> Collaborator | None: ...
