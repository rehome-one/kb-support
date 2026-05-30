"""Cursor-пагинация списка заявок (NFR-2.3) + спецификации сортировки.

Keyset-пагинация по тотальному порядку `(sort_expr <dir>, id <dir>)`; `id` —
уникальный tiebreaker. Курсор opaque: `base64url(json({"v": sort_value, "id": uuid}))`.

Особенности:
- `priority` сортируется по семантическому рангу (low<normal<high<critical), не
  алфавитно (в БД хранится строкой).
- `resolution_due_at` nullable (в E1 всегда NULL — SLA это E4): нормализуется
  COALESCE к sentinel-дате по направлению (NULLS LAST), чтобы keyset был корректен.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, and_, case, func, or_

from api.tickets.enums import TicketPriority
from api.tickets.models import Ticket

TicketSortKey = Literal[
    "created_at",
    "-created_at",
    "resolution_due_at",
    "-resolution_due_at",
    "priority",
    "-priority",
]

DEFAULT_SORT: TicketSortKey = "-created_at"

# Sentinel-даты (tz-aware, UTC) для NULLS LAST по resolution_due_at.
_MIN_DT = datetime.datetime(1, 1, 1, tzinfo=datetime.UTC)
_MAX_DT = datetime.datetime(9999, 12, 31, 23, 59, 59, tzinfo=datetime.UTC)

# Семантический ранг приоритета для сортировки.
_PRIORITY_RANK: dict[str, int] = {
    TicketPriority.LOW.value: 0,
    TicketPriority.NORMAL.value: 1,
    TicketPriority.HIGH.value: 2,
    TicketPriority.CRITICAL.value: 3,
}


@dataclass(frozen=True)
class SortSpec:
    """Разобранный sort-ключ: какой столбец и направление."""

    field: Literal["created_at", "resolution_due_at", "priority"]
    descending: bool


_SORTS: dict[str, SortSpec] = {
    "created_at": SortSpec("created_at", False),
    "-created_at": SortSpec("created_at", True),
    "resolution_due_at": SortSpec("resolution_due_at", False),
    "-resolution_due_at": SortSpec("resolution_due_at", True),
    "priority": SortSpec("priority", False),
    "-priority": SortSpec("priority", True),
}


def get_sort_spec(sort: str | None) -> SortSpec:
    """Вернуть SortSpec для ключа (по умолчанию -created_at)."""
    return _SORTS[sort] if sort in _SORTS else _SORTS[DEFAULT_SORT]


def _priority_rank() -> ColumnElement[Any]:
    return case(_PRIORITY_RANK, value=Ticket.priority, else_=0)


def order_expression(spec: SortSpec) -> ColumnElement[Any]:
    """Сортируемое выражение (с нормализацией NULL и ранга)."""
    if spec.field == "priority":
        return _priority_rank()
    if spec.field == "resolution_due_at":
        sentinel = _MIN_DT if spec.descending else _MAX_DT
        return func.coalesce(Ticket.resolution_due_at, sentinel)
    # InstrumentedAttribute — это ColumnElement в рантайме; cast снимает инвариантность стабов.
    return cast("ColumnElement[Any]", Ticket.created_at)


def order_by_clause(spec: SortSpec) -> list[ColumnElement[Any]]:
    expr = order_expression(spec)
    if spec.descending:
        return [expr.desc(), Ticket.id.desc()]
    return [expr.asc(), Ticket.id.asc()]


def row_cursor_value(ticket: Ticket, spec: SortSpec) -> Any:
    """JSON-сериализуемое значение sort-поля строки для курсора."""
    if spec.field == "priority":
        return _PRIORITY_RANK.get(ticket.priority, 0)
    if spec.field == "resolution_due_at":
        sentinel = _MIN_DT if spec.descending else _MAX_DT
        return (ticket.resolution_due_at or sentinel).isoformat()
    return ticket.created_at.isoformat()


def _sql_value(spec: SortSpec, raw: Any) -> Any:
    if spec.field == "priority":
        return int(raw)
    return datetime.datetime.fromisoformat(str(raw))


def keyset_predicate(spec: SortSpec, raw_value: Any, cursor_id: uuid.UUID) -> ColumnElement[bool]:
    """Условие «строго после курсора» по тотальному порядку (sort_expr, id)."""
    expr = order_expression(spec)
    value = _sql_value(spec, raw_value)
    if spec.descending:
        return or_(expr < value, and_(expr == value, Ticket.id < cursor_id))
    return or_(expr > value, and_(expr == value, Ticket.id > cursor_id))


def encode_cursor(value: Any, ticket_id: uuid.UUID) -> str:
    raw = json.dumps({"v": value, "id": str(ticket_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[Any, uuid.UUID]:
    """Разобрать курсор → (sort_value, id). Невалидный → ValueError."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        data = json.loads(raw)
        return data["v"], uuid.UUID(data["id"])
    except (binascii.Error, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise ValueError("invalid cursor") from exc
