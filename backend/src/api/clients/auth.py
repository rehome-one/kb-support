"""Общий источник m2m-токена для исходящих вызовов к соседям (E3, #71/#72).

`TokenProvider` абстрагирует получение Bearer-токена, чтобы реальный механизм
(Keycloak Client Credentials) подставился позже без правки адаптеров. Используется
и platform-клиентом (#71), и kb-search-клиентом (#72).

`StaticTokenProvider` — **только dev/test**: отдаёт токен из конфига-плейсхолдера.
Реальный `ClientCredentialsTokenProvider` — **#77** (ждёт провижининга m2m-realm).
НЕ должен быть боевым путём в prod-сборке: фабрика выбора провайдера обязана
fail-closed выбирать реальный провайдер в проде.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TokenProvider(Protocol):
    async def get_token(self) -> str: ...


class StaticTokenProvider:
    """DEV/TEST-only. Отдаёт фиксированный токен (из env-плейсхолдера). См. #77."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self) -> str:
        return self._token
