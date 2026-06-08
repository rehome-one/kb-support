"""HTTP-реализация возврата ответа в kb-search (E3-4, #72) поверх фундамента #70.

Провизорный контракт (ADR-0006 Решение 3) изолирован здесь. Идемпотентность —
Idempotency-Key = message_id (повтор не плодит дубль в сессии). Исходы:
202 → DELIVERED; 404/409 → SESSION_GONE (сессия истекла/закрыта); сетевой сбой /
circuit-open → DEGRADED. В лог НЕ попадает тело сообщения (ФЗ-152) — только
chat_session_id/message_id/исход (идентификаторы, не контент).
"""

from __future__ import annotations

from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.kb_search.models import (
    ArticleSuggestion,
    OperatorReply,
    ReplyOutcome,
    StatusNotification,
)
from api.observability.logging import get_logger

_logger = get_logger("clients.kb_search")

_SESSION_GONE_STATUSES = frozenset({404, 409})


class HttpKbSearchClient:
    """`KbSearchClient` поверх `ResilientHttpClient` (#70). Зависимости инъектируются."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def send_operator_reply(self, reply: OperatorReply) -> ReplyOutcome:
        path = f"/api/v1/chat/sessions/{reply.chat_session_id}/operator-reply"
        token = await self._token_provider.get_token()
        # provisional contract, see ADR-0006 Решение 3.
        body = {
            "ticket_id": str(reply.ticket_id),
            "message_id": str(reply.message_id),
            "body": reply.body,
            "author": "operator",
            "sent_at": reply.sent_at.isoformat(),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(reply.message_id),
        }
        try:
            response = await self._http.request(
                "POST", path, operation="send_operator_reply", headers=headers, json=body
            )
        except ExternalServiceError:
            # Включает CircuitOpenError. Тело не утекает (инвариант #70).
            _logger.warning(
                "kb-search reply degraded: session=%s message=%s",
                reply.chat_session_id,
                reply.message_id,
            )
            return ReplyOutcome.DEGRADED

        if response.status_code in _SESSION_GONE_STATUSES:
            _logger.warning(
                "kb-search reply: session gone (status=%d) session=%s message=%s",
                response.status_code,
                reply.chat_session_id,
                reply.message_id,
            )
            return ReplyOutcome.SESSION_GONE
        if response.status_code >= 400:
            _logger.warning(
                "kb-search reply degraded: status=%d session=%s message=%s",
                response.status_code,
                reply.chat_session_id,
                reply.message_id,
            )
            return ReplyOutcome.DEGRADED

        return ReplyOutcome.DELIVERED

    async def send_status_notification(self, notification: StatusNotification) -> ReplyOutcome:
        # Выделенный путь (E7-8, #149): отдельный провизорный endpoint, НЕ operator-reply
        # (у статуса нет message_id). Идемпотентность — Idempotency-Key = ticket:status.
        path = f"/api/v1/chat/sessions/{notification.chat_session_id}/status-notification"
        token = await self._token_provider.get_token()
        # provisional contract, see ADR-0006 (форма уточнится с боевым kb-search).
        body = {
            "ticket_id": str(notification.ticket_id),
            "status": notification.status,
            "status_label": notification.status_label,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"{notification.ticket_id}:{notification.status}",
        }
        try:
            response = await self._http.request(
                "POST", path, operation="send_status_notification", headers=headers, json=body
            )
        except ExternalServiceError:
            _logger.warning(
                "kb-search status degraded: session=%s ticket=%s",
                notification.chat_session_id,
                notification.ticket_id,
            )
            return ReplyOutcome.DEGRADED

        if response.status_code in _SESSION_GONE_STATUSES:
            _logger.warning(
                "kb-search status: session gone (status=%d) session=%s ticket=%s",
                response.status_code,
                notification.chat_session_id,
                notification.ticket_id,
            )
            return ReplyOutcome.SESSION_GONE
        if response.status_code >= 400:
            _logger.warning(
                "kb-search status degraded: status=%d session=%s ticket=%s",
                response.status_code,
                notification.chat_session_id,
                notification.ticket_id,
            )
            return ReplyOutcome.DEGRADED

        return ReplyOutcome.DELIVERED

    async def suggest_articles(self, query: str) -> list[ArticleSuggestion] | None:
        """Поиск статей БЗ по тексту (FR-5.4, #130). provisional contract, see ADR-0009.

        200 → список (возможно пустой); сетевой сбой/circuit-open/4xx-5xx/битый JSON →
        `None` (деградация AT-003). В лог не попадает текст запроса (ФЗ-152 — может нести
        фрагменты обращения), только operation/status."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await self._http.request(
                "POST",
                "/api/v1/search",
                operation="suggest_articles",
                headers=headers,
                json={"query": query},
            )
        except ExternalServiceError as exc:
            _logger.warning("kb-search suggest degraded: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            _logger.warning("kb-search suggest degraded: status=%d", response.status_code)
            return None
        try:
            payload = response.json()
            results: list[dict[str, Any]] = payload["results"]
            return [
                ArticleSuggestion(slug=r["slug"], title=r["title"], url=r.get("url"))
                for r in results
            ]
        except (ValueError, KeyError, TypeError):
            _logger.warning("kb-search suggest degraded: malformed response")
            return None
