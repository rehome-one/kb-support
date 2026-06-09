"""HTTP-реализация клиента BankProvider (E10-7, #197) поверх фундамента #70.

Провизорный контракт BankProvider API (ADR-0014, стиль ADR-0006/0010) изолирован
ЗДЕСЬ: `_map_payout_result` мапит провизорный JSON → доменный `PayoutResult`. Смена
upstream = правка только маппера (+ADR).

Деградация (AT-003, ADR-0010 Реш.4): выплата — мутация, «мягкого» `None` нет.
Недоступность соседа (timeout/5xx/circuit-open) → база бросает `ExternalServiceError`/
`CircuitOpenError` — НЕ ловим. 4xx и битый JSON → WARN (только operation/status) + raise.
В лог/исключение НЕ попадают суммы/ПДн (ФЗ-152). Запрос НЕ кешируется (мутация).
"""

from __future__ import annotations

from typing import Any

from api.clients.auth import TokenProvider
from api.clients.bank.models import PayoutRequest, PayoutResult
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.observability.logging import get_logger

_logger = get_logger("clients.bank")


def _map_payout_result(d: dict[str, Any]) -> PayoutResult:  # provisional contract, ADR-0014
    return PayoutResult(payment_id=str(d["payment_id"]))


class HttpBankProviderClient:
    """`BankProviderClient` поверх `ResilientHttpClient` (#70). provisional contract,
    ADR-0014. Зависимости инъектируются явно (тесты — без сети). Config-gate (пустой
    токен → клиент не создаётся) — забота фабрики потребителя, не этого класса."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def release_payout(self, request: PayoutRequest) -> PayoutResult:
        """Запросить выплату. 2xx+валидный JSON → `PayoutResult`. Бросает
        `ExternalServiceError`/`CircuitOpenError` при недоступности соседа, 4xx и битом JSON.
        Идемпотентность — по `reference`/ticket_id на стороне банка (провизорный контракт)."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        # provisional contract: POST запроса выплаты (ADR-0014). Суммы как строки (точность).
        response = await self._http.request(
            "POST",
            "/api/v1/payouts",
            operation="release_payout",
            headers=headers,
            json={
                "ticket_id": str(request.ticket_id),
                "amount": str(request.amount),
                "currency": request.currency,
                "reference": request.reference,
            },
        )

        if response.status_code >= 400:
            _logger.warning("bank release_payout rejected: status=%d", response.status_code)
            raise ExternalServiceError("bank", "release_payout", f"status={response.status_code}")

        try:
            payload: dict[str, Any] = response.json()
            return _map_payout_result(payload)
        except (ValueError, KeyError, TypeError) as exc:
            _logger.warning(
                "bank release_payout malformed response: status=%d", response.status_code
            )
            raise ExternalServiceError("bank", "release_payout", "malformed response") from exc
