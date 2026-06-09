"""HTTP-реализация PaymentReleaseChecker (E10-7, #197) поверх фундамента #70.

Провизорный контракт (ADR-0014, стиль ADR-0006) изолирован ЗДЕСЬ: `_map_clearance`.
Деградация (AT-003, мягкая — чтение, как platform #71): недоступность соседа
(`ExternalServiceError`/`CircuitOpenError`), не-200 или битый JSON → `None` + WARN
(проверка информационна, case_state не блокирует — ADR-0014 U4). Без ПДн в логах.
"""

from __future__ import annotations

import uuid
from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import CircuitOpenError, ExternalServiceError
from api.clients.payment_checker.models import Clearance
from api.observability.logging import get_logger

_logger = get_logger("clients.payment_checker")


def _map_clearance(d: dict[str, Any]) -> Clearance:  # provisional contract, ADR-0014
    reason = d.get("reason")
    return Clearance(
        clearable=bool(d["clearable"]), reason=str(reason) if reason is not None else None
    )


class HttpPaymentReleaseCheckerClient:
    """`PaymentReleaseCheckerClient` поверх `ResilientHttpClient` (#70). provisional
    contract, ADR-0014. Config-gate (пустой токен → клиент не создаётся) — у фабрики."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def check_clearance(self, ticket_id: uuid.UUID) -> Clearance | None:
        """Проверить возможность выплаты. 200+валидный JSON → `Clearance`; иначе `None`
        (деградация мягкая — проверка информационна, ADR-0014 U4)."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            # provisional contract: GET проверки клиринга по заявке (ADR-0014).
            response = await self._http.request(
                "GET",
                "/api/v1/clearance",
                operation="check_clearance",
                headers=headers,
                params={"ticket_id": str(ticket_id)},
            )
        except (ExternalServiceError, CircuitOpenError):
            _logger.warning("payment_checker unavailable: ticket=%s", ticket_id)
            return None

        if response.status_code != 200:
            _logger.warning("payment_checker non-200: status=%d", response.status_code)
            return None
        try:
            payload: dict[str, Any] = response.json()
            return _map_clearance(payload)
        except (ValueError, KeyError, TypeError):
            _logger.warning("payment_checker malformed response: status=%d", response.status_code)
            return None
