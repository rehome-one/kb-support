"""Readiness-проверки зависимостей сервиса (БД; Redis/external — позже)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def check_database(session: AsyncSession) -> None:
    """`SELECT 1` — бросает исключение, если БД недоступна."""
    await session.execute(text("SELECT 1"))
