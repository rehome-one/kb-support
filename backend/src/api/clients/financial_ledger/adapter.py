"""HTTP-реализация FinancialLedger (E10-7 PR-2, #197) поверх фундамента #70.

Провизорный контракт (ADR-0014) изолирован ЗДЕСЬ: `_map_result`. Деградация (AT-003,
мутация → raise, как bank/kb-files #143): недоступность соседа (timeout/5xx/circuit-open)
→ база бросает `ExternalServiceError`/`CircuitOpenError`; 4xx и битый JSON → WARN
(operation/status) + raise. Суммы/ПДн НЕ в логах (ФЗ-152). Не кешируется (мутация).
"""

from __future__ import annotations

from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.financial_ledger.models import LedgerEntry, LedgerResult
from api.observability.logging import get_logger

_logger = get_logger("clients.financial_ledger")


def _map_result(d: dict[str, Any]) -> LedgerResult:  # provisional contract, ADR-0014
    return LedgerResult(entry_id=str(d["entry_id"]))


class HttpFinancialLedgerClient:
    """`FinancialLedgerClient` поверх `ResilientHttpClient` (#70). provisional contract,
    ADR-0014. Config-gate (пустой токен → клиент не создаётся) — у вызывающего fire-after."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def record_entry(self, entry: LedgerEntry) -> LedgerResult:
        """Записать проводку-ссылку решения. 2xx+валидный JSON → `LedgerResult`. Бросает
        `ExternalServiceError`/`CircuitOpenError` при недоступности соседа, 4xx и битом JSON."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        # provisional contract: POST проводки (ADR-0014). Сумма строкой (точность); None — REJECTED.
        response = await self._http.request(
            "POST",
            "/api/v1/entries",
            operation="record_entry",
            headers=headers,
            json={
                "ticket_id": str(entry.ticket_id),
                "decision": entry.decision,
                "amount": str(entry.amount) if entry.amount is not None else None,
                "reference": entry.reference,
            },
        )

        if response.status_code >= 400:
            _logger.warning("ledger record_entry rejected: status=%d", response.status_code)
            raise ExternalServiceError(
                "financial_ledger", "record_entry", f"status={response.status_code}"
            )

        try:
            payload: dict[str, Any] = response.json()
            return _map_result(payload)
        except (ValueError, KeyError, TypeError) as exc:
            _logger.warning(
                "ledger record_entry malformed response: status=%d", response.status_code
            )
            raise ExternalServiceError(
                "financial_ledger", "record_entry", "malformed response"
            ) from exc
