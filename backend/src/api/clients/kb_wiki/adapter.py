"""HTTP-реализация клиента kb-wiki (E6-5, #129) поверх фундамента #70.

Провизорный контракт kb-wiki API (ADR-0009 Решение 3, стиль ADR-0006) изолирован ЗДЕСЬ.
Деградация (AT-003): недоступность соседа/circuit-open/прочая 4xx-5xx → `None` (валидация
не блокирует); 404 → `False` (подтверждённое отсутствие → 422 на стороне CRUD); 200 →
`True`. В лог НЕ попадает тело/slug-ПДн — только operation/status (slug — не ПДн, но и не
логируется во избежание шума). Read-only: только GET.
"""

from __future__ import annotations

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.observability.logging import get_logger

_logger = get_logger("clients.kb_wiki")


class HttpKbWikiClient:
    """kb-wiki поверх ResilientHttpClient. provisional contract, see ADR-0009/ADR-0006."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token_provider = token_provider

    async def article_exists(self, slug: str) -> bool | None:
        """200 → True; 404 → False (подтверждённо нет); ошибка/прочее → None (деградация)."""
        token = await self._token_provider.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            # provisional contract: путь статьи kb-wiki по slug (см. ADR-0009 Решение 3).
            response = await self._http.request(
                "GET", f"/api/v1/articles/{slug}", operation="get_article", headers=headers
            )
        except ExternalServiceError as exc:
            # Включает CircuitOpenError. Тело ответа не утекает (инвариант #70).
            _logger.warning("kb_wiki get_article degraded: %s", type(exc).__name__)
            return None
        if response.status_code == 404:
            return False  # подтверждённое отсутствие
        if response.status_code >= 400:
            _logger.warning("kb_wiki get_article degraded: status=%d", response.status_code)
            return None
        return True
