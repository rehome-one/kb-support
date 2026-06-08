"""Серверные RU-метки статусов и набор уведомляемых статусов (E7-8, #149).

Бэк НЕ импортирует фронтовый `format.ts` (арх-константа: отдельные модули) — здесь
своя карта меток для тел уведомлений. `NOTIFIED_STATUSES` — статусы, о смене на
которые уведомляем заявителя (решение Архитектора Д1): RESOLVED/CLOSED/PENDING.
WAITING = «ждёт 3-ю сторону» (НЕ заявитель) — не уведомляем.
"""

from __future__ import annotations

from api.tickets.enums import TicketStatus

STATUS_LABELS: dict[str, str] = {
    TicketStatus.NEW.value: "Новая",
    TicketStatus.OPEN.value: "В работе",
    TicketStatus.PENDING.value: "Ожидает вашего ответа",
    TicketStatus.WAITING.value: "Ожидает третьей стороны",
    TicketStatus.ESCALATED.value: "Эскалирована",
    TicketStatus.RESOLVED.value: "Решена",
    TicketStatus.CLOSED.value: "Закрыта",
    TicketStatus.REOPENED.value: "Переоткрыта",
}

# Решение Архитектора Д1: уведомляем заявителя о смене на эти статусы.
NOTIFIED_STATUSES: frozenset[str] = frozenset(
    {
        TicketStatus.RESOLVED.value,
        TicketStatus.CLOSED.value,
        TicketStatus.PENDING.value,
    }
)


def status_label(status: str) -> str:
    """RU-метка статуса (фолбэк — само значение, если неизвестно)."""
    return STATUS_LABELS.get(status, status)
