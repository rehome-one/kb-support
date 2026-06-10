"""HTTP-реализация AcceptanceAct (E10-9 PR-A, #199) поверх фундамента #70.

Провизорный контракт (ADR-0016/0014) изолирован ЗДЕСЬ: `_map_act`. Деградация (AT-003,
мягкая — чтение): недоступность соседа (`ExternalServiceError`/`CircuitOpenError`), не-200
или битый JSON → `None` + WARN. Без ПДн в логах (только id/operation/status, ФЗ-152).
"""

from __future__ import annotations

import decimal
import uuid
from typing import Any

from api.clients.acceptance_act.models import AcceptanceAct
from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import CircuitOpenError, ExternalServiceError
from api.observability.logging import get_logger

_logger = get_logger("clients.acceptance_act")


def _map_act(d: dict[str, Any]) -> AcceptanceAct:  # provisional contract, ADR-0016/0014
    damage = d.get("damage_amount")
    return AcceptanceAct(
        id=str(d["id"]),
        kind=str(d["kind"]),
        signing_status=str(d["signing_status"]),
        damage_amount=decimal.Decimal(str(damage)) if damage is not None else None,
    )


class HttpAcceptanceActClient:
    """`AcceptanceActClient` поверх `ResilientHttpClient` (#70). provisional contract,
    ADR-0016. Config-gate (пустой токен → клиент не создаётся) — у фабрики."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def get_act(self, acceptance_act_id: uuid.UUID) -> AcceptanceAct | None:
        """Резолв акта. 200+валидный JSON → `AcceptanceAct`; иначе `None` (мягкая деградация)."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            # provisional contract: GET акта по id (ADR-0014 таблица / ADR-0016 D1).
            response = await self._http.request(
                "GET",
                f"/api/v1/acts/{acceptance_act_id}",
                operation="get_act",
                headers=headers,
            )
        except (ExternalServiceError, CircuitOpenError):
            _logger.warning("acceptance_act unavailable: act=%s", acceptance_act_id)
            return None

        if response.status_code != 200:
            _logger.warning("acceptance_act non-200: status=%d", response.status_code)
            return None
        try:
            payload: dict[str, Any] = response.json()
            return _map_act(payload)
        except (ValueError, KeyError, TypeError, decimal.InvalidOperation):
            _logger.warning("acceptance_act malformed response: status=%d", response.status_code)
            return None
