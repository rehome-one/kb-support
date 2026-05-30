"""SQLAlchemy declarative base для ORM-моделей kb-support.

Все ORM модели (Ticket, TicketMessage, TicketHistory, CannedResponse, ...)
наследуются от `Base`. На bootstrap'е (#2) — минимум; type_annotation_map
и shared mixin'ы будут добавлены по мере появления моделей в #5+.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """DeclarativeBase для всех ORM моделей."""

    pass
