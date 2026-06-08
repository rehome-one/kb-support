"""Дедуп-маркер статус-уведомлений в `ticket.custom_fields` (E7-8, #149, решение C).

Маркер — последний статус, о котором уже уведомили заявителя, чтобы не дублировать.
**Запись только РЕАССАЙНОМ словаря** (`ticket.custom_fields = {...}`): колонка — обычный
JSONB без `MutableDict`, in-place мутация НЕ трекается SQLAlchemy (см. ревью M1) →
маркер молча не сохранится. Сброс маркера при переходе ПРОЧЬ от уведомлённого статуса
(M2) — иначе `RESOLVED→REOPENED→RESOLVED` ложно подавит второй RESOLVED.
Запись выполняется В ТОЙ ЖЕ транзакции, что и смена статуса (без лишнего commit).
"""

from __future__ import annotations

from typing import Any

from api.tickets.models import Ticket

_BLOCK = "notifications"
_LAST = "last_status_notified"
_CTA = "rating_cta_sent"


def _block(ticket: Ticket) -> dict[str, Any]:
    cf = ticket.custom_fields or {}
    block = cf.get(_BLOCK)
    return dict(block) if isinstance(block, dict) else {}


def last_status_notified(ticket: Ticket) -> str | None:
    value = _block(ticket).get(_LAST)
    return value if isinstance(value, str) else None


def _write(ticket: Ticket, block: dict[str, Any]) -> None:
    # Реассайн всего словаря custom_fields — иначе SQLAlchemy не увидит изменение JSONB.
    cf = dict(ticket.custom_fields or {})
    if block:
        cf[_BLOCK] = block
    else:
        cf.pop(_BLOCK, None)
    ticket.custom_fields = cf


def set_status_notified(ticket: Ticket, status: str) -> None:
    """Запомнить, что о смене на `status` заявитель уведомлён."""
    block = _block(ticket)
    block[_LAST] = status
    _write(ticket, block)


def clear_status_notified(ticket: Ticket) -> None:
    """Сбросить маркер (M2) — при переходе прочь от уведомлённого статуса."""
    block = _block(ticket)
    if _LAST in block:
        block.pop(_LAST)
        _write(ticket, block)


def rating_cta_sent(ticket: Ticket) -> bool:
    """Был ли уже отправлен email-CTA «оцени заявку» (FR-8.1, #184) — дедуп."""
    return _block(ticket).get(_CTA) is True


def set_rating_cta_sent(ticket: Ticket) -> None:
    """Пометить, что CTA отправлен (через общий блок — сосуществует с last_status_notified;
    read-modify-reassign, чтобы не перетереть статус-маркер в той же транзакции). НЕ
    сбрасывается при reopen — один CTA на заявку (ADR-0012 D3)."""
    block = _block(ticket)
    block[_CTA] = True
    _write(ticket, block)
