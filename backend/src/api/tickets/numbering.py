"""Генерация человекочитаемого номера заявки `RH-YYYY-NNNNN` (ТЗ §3.1).

N берётся из PostgreSQL-sequence `ticket_number_seq` (конкуррентно-безопасно).
Per-year reset на E1 НЕ реализован — N глобально монотонный; уникальность
гарантируют sequence + unique-constraint на `Ticket.number`. Год — текущий (UTC).
"""

from __future__ import annotations

import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TICKET_NUMBER_SEQUENCE = "ticket_number_seq"
_NEXTVAL_SQL = text(f"SELECT nextval('{TICKET_NUMBER_SEQUENCE}')")


def format_ticket_number(year: int, seq: int) -> str:
    """Собрать номер из года и порядкового значения (мин. 5 цифр)."""
    return f"RH-{year}-{seq:05d}"


async def generate_ticket_number(
    session: AsyncSession, *, now: datetime.datetime | None = None
) -> str:
    """Сгенерировать следующий уникальный номер заявки через sequence."""
    year = (now or datetime.datetime.now(datetime.UTC)).year
    result = await session.execute(_NEXTVAL_SQL)
    return format_ticket_number(year, int(result.scalar_one()))
