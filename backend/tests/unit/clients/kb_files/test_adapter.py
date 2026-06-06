"""Тесты клиента kb-files (E7-1, #143): upload, raise-деградация, auth, ПДн в логах.

httpx.MockTransport + инжектируемые clock/sleep (детерминизм). 2xx+валид → StoredFile;
недоступность соседа (5xx/сеть) → пробрасывание ExternalServiceError (база #70); 4xx и
битый JSON → raise ExternalServiceError (ADR-0010 Решение 4 — типизированная ошибка, НЕ
None). filename (потенциальные ПДн) НЕ попадает в логи и в текст исключения."""

from __future__ import annotations

from collections.abc import Callable
from unittest import mock

import httpx
import pytest

from api.clients import kb_files
from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.errors import ExternalServiceError
from api.clients.kb_files import adapter as adapter_module
from api.clients.kb_files.adapter import HttpKbFilesClient
from api.clients.retry import RetryPolicy

_PII_FILENAME = "паспорт-ivanov-ivan@example.com.pdf"


async def _noop_sleep(_: float) -> None:
    return None


def _make(
    handler: Callable[[httpx.Request], httpx.Response], *, attempts: int = 2
) -> HttpKbFilesClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://kb-files")
    rc = ResilientHttpClient(
        client_name="kb_files",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts, base_delay=0.01, max_delay=0.01),
        sleep=_noop_sleep,
        monotonic=lambda: 0.0,
    )
    return HttpKbFilesClient(http_client=rc, token_provider=StaticTokenProvider("test-token"))


async def _upload(client: HttpKbFilesClient, filename: str = "doc.pdf") -> object:
    return await client.upload(filename=filename, content_type="application/pdf", content=b"data")


async def test_200_returns_stored_file() -> None:
    body = {
        "id": "11111111-1111-1111-1111-111111111111",
        "filename": "doc.pdf",
        "content_type": "application/pdf",
        "size": 4,
    }
    client = _make(lambda req: httpx.Response(201, json=body))
    result = await _upload(client)
    assert result == kb_files.StoredFile(
        id="11111111-1111-1111-1111-111111111111",
        filename="doc.pdf",
        content_type="application/pdf",
        size=4,
    )


async def test_network_error_propagates() -> None:
    def _boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _make(_boom, attempts=1)
    with pytest.raises(ExternalServiceError):
        await _upload(client)


async def test_5xx_propagates() -> None:
    client = _make(lambda req: httpx.Response(503), attempts=1)
    with pytest.raises(ExternalServiceError):
        await _upload(client)


async def test_4xx_raises() -> None:
    client = _make(lambda req: httpx.Response(413))  # payload too large
    with pytest.raises(ExternalServiceError):
        await _upload(client)


async def test_malformed_2xx_raises_and_no_pii() -> None:
    # 2xx, но контракт разошёлся (нет ключа id) — деградация типизированной ошибкой.
    client = _make(lambda req: httpx.Response(200, json={"filename": _PII_FILENAME}))
    with (
        mock.patch.object(adapter_module._logger, "warning") as warn,
        pytest.raises(ExternalServiceError) as exc_info,
    ):
        await _upload(client, filename=_PII_FILENAME)
    # ФЗ-152: filename не в логах и не в тексте исключения.
    logged = " ".join(str(a) for call in warn.call_args_list for a in call.args)
    assert _PII_FILENAME not in logged
    assert _PII_FILENAME not in str(exc_info.value)


async def test_4xx_does_not_log_filename() -> None:
    client = _make(lambda req: httpx.Response(422))
    with (
        mock.patch.object(adapter_module._logger, "warning") as warn,
        pytest.raises(ExternalServiceError),
    ):
        await _upload(client, filename=_PII_FILENAME)
    logged = " ".join(str(a) for call in warn.call_args_list for a in call.args)
    assert _PII_FILENAME not in logged


async def test_sends_bearer_token_and_multipart() -> None:
    seen: dict[str, object] = {}

    def _handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("Authorization", "")
        seen["ctype"] = req.headers.get("Content-Type", "")
        return httpx.Response(
            201,
            json={
                "id": "22222222-2222-2222-2222-222222222222",
                "filename": "doc.pdf",
                "content_type": "application/pdf",
                "size": 4,
            },
        )

    client = _make(_handler)
    await _upload(client)
    assert seen["auth"] == "Bearer test-token"
    assert "multipart/form-data" in str(seen["ctype"])
