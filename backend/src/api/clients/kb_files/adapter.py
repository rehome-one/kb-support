"""HTTP-реализация клиента kb-files (E7-1, #143) поверх фундамента #70.

Провизорный контракт kb-files API (ADR-0010 Решение 4, стиль ADR-0006) изолирован
ЗДЕСЬ: `_map_stored_file` мапит провизорный JSON → доменный `StoredFile`. Смена
upstream = правка только маппера (+ADR).

Деградация (AT-003, ADR-0010 Решение 4 — «типизированная ошибка, решает вызывающий»):
загрузка — мутация, «мягкого» `None` нет. Недоступность соседа (timeout/5xx/
circuit-open) → база (`ResilientHttpClient`) бросает `ExternalServiceError`/
`CircuitOpenError` — НЕ ловим, пробрасываем. 4xx и битый/неполный JSON → WARN
(только `operation`/`status`) + `raise ExternalServiceError`. В лог и в текст
исключения НЕ попадает `filename`/тело (ФЗ-152) — только `operation`/`status`.
Загрузка НЕ кешируется (мутация).
"""

from __future__ import annotations

from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.kb_files.models import StoredFile
from api.observability.logging import get_logger

_logger = get_logger("clients.kb_files")


def _map_stored_file(d: dict[str, Any]) -> StoredFile:  # provisional contract, see ADR-0010
    return StoredFile(
        id=str(d["id"]),
        filename=d["filename"],
        content_type=d["content_type"],
        size=int(d["size"]),
    )


class HttpKbFilesClient:
    """`KbFilesClient` поверх `ResilientHttpClient` (#70). provisional contract,
    see ADR-0010 Решение 4 / ADR-0006.

    Зависимости инъектируются явно (тесты — без сети). Config-gate (пустой токен →
    клиент не создаётся) — забота фабрики потребителя (#145), не этого класса."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def upload(self, *, filename: str, content_type: str, content: bytes) -> StoredFile:
        """Загрузить вложение в kb-files. 2xx+валидный JSON → `StoredFile`.

        Бросает `ExternalServiceError`/`CircuitOpenError` при недоступности соседа
        (из `ResilientHttpClient`), 4xx и битом/неполном JSON. Решение о судьбе
        вложения — у вызывающего (ADR-0010 Решение 4)."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        # provisional contract: POST multipart на endpoint загрузки kb-files (ADR-0010 Реш.4).
        response = await self._http.request(
            "POST",
            "/api/v1/files",
            operation="upload",
            headers=headers,
            files={"file": (filename, content, content_type)},
        )

        if response.status_code >= 400:
            # Сосед отверг файл. Тело не утекает (ФЗ-152) — только статус.
            _logger.warning("kb_files upload rejected: status=%d", response.status_code)
            raise ExternalServiceError("kb_files", "upload", f"status={response.status_code}")

        try:
            payload: dict[str, Any] = response.json()
            return _map_stored_file(payload)
        except (ValueError, KeyError, TypeError) as exc:
            # 2xx, но контракт разошёлся / тело не JSON. filename не логируем (ПДн).
            _logger.warning("kb_files upload malformed response: status=%d", response.status_code)
            raise ExternalServiceError("kb_files", "upload", "malformed response") from exc
