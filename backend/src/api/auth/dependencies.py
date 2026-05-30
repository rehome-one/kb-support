"""FastAPI-зависимости аутентификации.

`get_current_principal` — единая точка получения `Principal` для эндпоинтов.

**E1 seam (вариант A, решение Архитектора 2026-05-30).** Верификатора токена/
сессии ещё нет (Keycloak Bearer JWT RS256/JWKS + CookieAuth — issue #29, до E2),
поэтому зависимость **fail-closed**: возвращает 401. Это сознательно: вся логика
контроля доступа и security-тесты реальны, в тестах принципал инжектится через
`app.dependency_overrides[get_current_principal]` (штатный паттерн FastAPI, не
прод-костыль). #29 заменит реализацию, не меняя сигнатуру.
"""

from __future__ import annotations

from api.auth.principal import Principal
from api.errors import ProblemException


async def get_current_principal() -> Principal:
    """Вернуть аутентифицированного субъекта запроса.

    До #29 аутентификация не сконфигурирована → fail-closed (401). В тестах
    переопределяется через `dependency_overrides`.
    """
    raise ProblemException.unauthorized(
        detail="Authentication is not configured yet (pending #29).",
    )
