"""Модель аутентифицированного субъекта (`Principal`) для RBAC kb-support.

Результат верификации токена/сессии. Интерфейс зафиксирован на E1 (#6); реальный
верификатор (Keycloak JWT RS256/JWKS, CookieAuth) наполнит модель в #29 без
изменения сигнатуры: `sub` → `user_id`, realm/client-роли → `teams`/`scopes`.

См. ADR-0003 (контуры), NFR-1.2 (RBAC), CLAUDE.md (scope считается только
бэкендом из проверенного токена — не из payload).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field

from api.auth.scopes import STAFF_ADMIN_SCOPE
from api.tickets.enums import TicketTeam


class PrincipalKind(str, enum.Enum):
    """Тип субъекта.

    REQUESTER — заявитель (видит только свои заявки). OPERATOR — сотрудник
    поддержки (видит заявки своих команд). SERVICE — m2m-вызов (напр. kb-search
    при эскалации из чата, E3).
    """

    REQUESTER = "requester"
    OPERATOR = "operator"
    SERVICE = "service"


@dataclass(frozen=True)
class Principal:
    """Аутентифицированный субъект запроса.

    `teams` заполняется для операторов и определяет видимость заявок по командам
    (storage-level фильтр, NFR-1.2). `scopes` — гранулярные права из токена.
    """

    user_id: uuid.UUID
    kind: PrincipalKind
    scopes: frozenset[str] = field(default_factory=frozenset)
    teams: frozenset[TicketTeam] = field(default_factory=frozenset)

    @property
    def is_operator(self) -> bool:
        """Является ли субъект оператором (доступ к заявкам по командам)."""
        return self.kind is PrincipalKind.OPERATOR

    @property
    def is_staff_admin(self) -> bool:
        """Есть ли у субъекта админ-скоуп (настройка SLA/business hours, §6).

        Гранулярное право из проверенного токена — не привязано к `kind` (оператор
        с этим скоупом администрирует конфигурацию; см. `auth/scopes.py`)."""
        return STAFF_ADMIN_SCOPE in self.scopes
