"""Интерфейс клиента kb-files (E7-1, #143).

Потребитель (#145 ingestion email / #148 веб-форма) зависит от этого Protocol и
DTO, не от HTTP-реализации/провизорной формы. `upload` — мутация: при сбое
(AT-003) бросает типизированную ошибку (`ExternalServiceError`/`CircuitOpenError`),
решение о судьбе вложения принимает вызывающий (ADR-0010 Решение 4). НЕ `None` —
у загрузки нет «мягкой» деградации: потеря файла обязана быть видимой.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.kb_files.models import StoredFile


@runtime_checkable
class KbFilesClient(Protocol):
    async def upload(self, *, filename: str, content_type: str, content: bytes) -> StoredFile: ...
