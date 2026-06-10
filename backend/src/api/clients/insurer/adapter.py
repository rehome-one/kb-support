"""HTTP-реализация клиента страховщика (E10-10 PR-B #200) поверх фундамента #70.

Провизорный контракт (ADR-0014:67/0017) изолирован ЗДЕСЬ. Деградация (AT-003, ADR-0010
Реш.4): передача — мутация, «мягкого» None нет. Недоступность соседа (timeout/5xx/circuit-
open) → база бросает `ExternalServiceError`/`CircuitOpenError` — НЕ ловим. 4xx → WARN
(только operation/status) + raise. ПДн/тело в лог/исключение НЕ попадают (ФЗ-152).
"""

from __future__ import annotations

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.insurer.models import InsurerEvent
from api.observability.logging import get_logger

_logger = get_logger("clients.insurer")


class HttpInsurerClient:
    """`InsurerClient` поверх `ResilientHttpClient` (#70). provisional contract, ADR-0014:67."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def send_event(self, event: InsurerEvent) -> None:
        """Передать событие страховщику. 2xx → ok; недоступность/4xx → raise (мутация)."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        # provisional contract: POST события (ADR-0014:67). Только id, без ПДн.
        response = await self._http.request(
            "POST",
            "/api/v1/events",
            operation="send_event",
            headers=headers,
            json={
                "ticket_id": str(event.ticket_id),
                "insurance_event_id": (
                    str(event.insurance_event_id) if event.insurance_event_id else None
                ),
            },
        )
        if response.status_code >= 400:
            _logger.warning("insurer send_event rejected: status=%d", response.status_code)
            raise ExternalServiceError("insurer", "send_event", f"status={response.status_code}")
