"""FastAPI application entry point для kb-support.

На bootstrap'е (#1) — минимальный skeleton с одним liveness-эндпоинтом.
`/readyz` с проверкой DB / Redis / external API появится в #13.
"""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from api import __version__

app = FastAPI(
    title="kb-support",
    description="Модуль службы поддержки reHome (helpdesk-ядро по ТЗ v2.2)",
    version=__version__,
)


class HealthzResponse(BaseModel):
    """Liveness probe response — фиксированная схема для контракта."""

    status: Literal["ok"]


@app.get(
    "/healthz",
    response_model=HealthzResponse,
    summary="Liveness probe",
    tags=["Infrastructure"],
)
def healthz() -> HealthzResponse:
    """Возвращает 200 OK всегда, если процесс жив.

    Не проверяет DB / Redis / external API — это сделает `/readyz` в #13.
    Используется Kubernetes liveness probe и balancer'ом для базового
    healthcheck'а.
    """
    return HealthzResponse(status="ok")
