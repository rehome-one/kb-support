"""Учёт пауз SLA при смене статуса заявки (E4-4 #88, FR-4.5).

**Решение Архитектора (ADR-0007 «Решение 2»): паузы = PENDING + WAITING** — время,
проведённое в этих статусах, не идёт в норматив РЕШЕНИЯ. На выходе из паузы
`resolution_due_at` сдвигается на длительность паузы; норматив первого ответа
(`first_response_due_at`) паузами НЕ двигается.

Чистая функция (`now` инъектируется) — без I/O и без `datetime.now()` внутри, чтобы
юнит-тесты задавали точные дельты. Вызывается из единственного чокпоинта смены
статуса `apply_status_side_effects` (оба пути: PATCH и action-эндпоинты).
"""

from __future__ import annotations

import datetime

from api.tickets.enums import TicketStatus
from api.tickets.models import Ticket

# Статусы-паузы (ADR-0007 Решение 2). Именованная константа — без магических строк.
_PAUSE_STATUSES = frozenset({TicketStatus.PENDING.value, TicketStatus.WAITING.value})


def apply_pause_accounting(ticket: Ticket, old_status: str, now: datetime.datetime) -> None:
    """Учесть вход/выход из паузы (PENDING/WAITING) при смене статуса.

    Вход (статус стал паузой) — зафиксировать начало. Выход (был паузой, стал не
    паузой) — накопить длительность и сдвинуть `resolution_due_at`. Переход между
    двумя паузами (PENDING↔WAITING) — пауза продолжается, начало не сбрасывается.
    """
    was_paused = old_status in _PAUSE_STATUSES
    is_paused = ticket.status in _PAUSE_STATUSES

    if is_paused and not was_paused:
        # Вход в паузу: запомнить начало (resolution_due_at пока не трогаем).
        ticket.sla_paused_at = now
        return

    if was_paused and not is_paused and ticket.sla_paused_at is not None:
        # Выход из паузы: накопить длительность и сдвинуть норматив решения.
        delta = now - ticket.sla_paused_at
        ticket.sla_paused_seconds += max(0, int(delta.total_seconds()))
        if ticket.resolution_due_at is not None:
            ticket.resolution_due_at = ticket.resolution_due_at + delta
        ticket.sla_paused_at = None
