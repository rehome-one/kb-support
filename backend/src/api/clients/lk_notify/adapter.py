"""HTTP-реализация доставки решения в ЛК (E10-7 PR-2, #197) поверх фундамента #70.

Провизорный контракт (ADR-0014/0006) изолирован ЗДЕСЬ. Цель — платформа rehome.one
(тот же сосед, что platform-клиент #71; конфиг переиспользуется — `platform_api_*`,
как containment #166 переиспользовал kb_search_*). Деградация (AT-003, мутация → raise):
недоступность/4xx/битый ответ → raise; ловит fire-after. reason/суммы НЕ в логах (ФЗ-152).
"""

from __future__ import annotations

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.lk_notify.models import DecisionNotification
from api.observability.logging import get_logger

_logger = get_logger("clients.lk_notify")


class HttpLkNotifyClient:
    """`LkNotifyClient` поверх `ResilientHttpClient` (#70). provisional contract, ADR-0014.
    Config-gate (пустой токен → клиент не создаётся) — у вызывающего fire-after."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def notify_decision(self, notification: DecisionNotification) -> None:
        """Доставить решение в ЛК заявителя. 2xx → успех. Бросает `ExternalServiceError`/
        `CircuitOpenError` при недоступности соседа или 4xx (ловит fire-after, best-effort)."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        # provisional contract: POST уведомления о решении в ЛК (ADR-0014). Сумма строкой.
        response = await self._http.request(
            "POST",
            f"/api/v1/claims/{notification.ticket_id}/decision-notification",
            operation="notify_decision",
            headers=headers,
            json={
                "requester_id": str(notification.requester_id),
                "decision": notification.decision,
                "approved_amount": (
                    str(notification.approved_amount)
                    if notification.approved_amount is not None
                    else None
                ),
                "reason": notification.reason,
            },
        )
        if response.status_code >= 400:
            _logger.warning("lk_notify decision rejected: status=%d", response.status_code)
            raise ExternalServiceError(
                "lk_notify", "notify_decision", f"status={response.status_code}"
            )
