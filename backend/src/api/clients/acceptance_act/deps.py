"""FastAPI-зависимость AcceptanceAct: per-request клиент (E10-9 PR-A, #199).

`get_acceptance_act_client` — per-request клиент или `None`, если интеграция выключена
(пустой `acceptance_act_api_token`). Паттерн `get_payment_release_checker_client` (#197):
config-gated, resilient AT-003 (#70). `StaticTokenProvider` — ТОЛЬКО dev/test; реальный
ClientCredentials — #77.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from api.clients.acceptance_act import AcceptanceActClient, HttpAcceptanceActClient
from api.clients.auth import StaticTokenProvider
from api.clients.factory import build_resilient_client
from api.config import get_settings


async def get_acceptance_act_client() -> AsyncIterator[AcceptanceActClient | None]:
    """AcceptanceAct-клиент или `None` (пустой токен → резолв выключен, инертно до #77)."""
    settings = get_settings()
    if not settings.acceptance_act_api_token:
        yield None
        return

    async with httpx.AsyncClient(
        base_url=settings.acceptance_act_api_base_url,
        timeout=settings.client_timeout_seconds,
    ) as http:
        yield HttpAcceptanceActClient(
            http_client=build_resilient_client("acceptance_act", http, settings),
            # TODO(#77): dev/test-only провайдер; боевой ClientCredentials — #77.
            token_provider=StaticTokenProvider(settings.acceptance_act_api_token),
        )
