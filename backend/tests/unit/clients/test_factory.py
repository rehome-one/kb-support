"""Тест общей сборки resilient-клиента (E10-7 PR-2, #197, NIT-1 ревью #213)."""

from __future__ import annotations

import httpx

from api.clients.base import ResilientHttpClient
from api.clients.factory import build_resilient_client
from api.config import Settings


def test_build_resilient_client_returns_wrapper() -> None:
    http = httpx.AsyncClient(base_url="http://x")
    client = build_resilient_client("svc", http, Settings())
    assert isinstance(client, ResilientHttpClient)
