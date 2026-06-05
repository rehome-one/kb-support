"""Подстановка переменных в шаблон ответа (E6-3 #127; FR-5.2, ADR-0009 Решение 1/2).

Чистая логика без I/O: `render_template` заменяет токены `{{var}}` ТОЛЬКО по белому списку
переданных переменных. Никакой логики/выражений/доступа к атрибутам (нет SSTI — отказ от
jinja2, ADR-0009 Реш.1). **Неизвестная/недоступная переменная остаётся как `{{var}}`** —
информативный плейсхолдер: оператор видит незаполненное и правит вручную (в т.ч.
`{{requester_name}}` до проводки platform/#77).

`build_local_variables` собирает доступные из своей БД переменные (без ПДн); ПДн
(`requester_name` из platform) добавляет вызывающий (render-эндпоинт, config-gated).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping

from api.tickets.models import Ticket

# Токен переменной: {{name}} с произвольными пробелами; name — идентификатор.
_TOKEN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_template(body: str, variables: Mapping[str, str]) -> str:
    """Подставить `{{var}}` из `variables`; неизвестные токены оставить как есть."""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        # .get с дефолтом = исходный токен: неизвестная переменная не теряется.
        return variables.get(name, match.group(0))

    return _TOKEN.sub(_replace, body)


def build_local_variables(ticket: Ticket, *, today: datetime.date) -> dict[str, str]:
    """Локальные переменные из своей БД (без ПДн). `today` инъектируется (чистота)."""
    return {
        "ticket_number": ticket.number,
        "ticket_subject": ticket.subject,
        "ticket_type": ticket.type,
        "current_date": today.isoformat(),
    }
