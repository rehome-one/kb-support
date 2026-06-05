"""ORM-модель шаблона ответа CannedResponse (E6-1 #125; §3.6 ТЗ, ADR-0009).

Конфиг-справочник **без ПДн** (ПДн появляются только при рендере #127, на сервере).
`type` — домен `TicketType`, хранится `String` + валидация Python-энумом на границе API
(#126; E1-конвенция, Issue #5 — без нативного PG ENUM). `linked_article_slug` — строка
(ссылка на статью kb-wiki), **НЕ FK** к чужой БД (арх-константа, ADR-0005 Решение 1):
существование slug проверяет HTTP-клиент kb-wiki (#129), не БД. `usage_count` —
счётчик использований, инкремент при ответе из шаблона (#128).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, TimestampMixin


class CannedResponse(TimestampMixin, Base):
    """Шаблон ответа оператора (§3.6 ТЗ).

    `body` несёт переменные `{{requester_name}}`, `{{ticket_number}}` и т.п. —
    подстановка по белому списку при рендере (#127). `type` (nullable) ограничивает
    применимость шаблона типом обращения. Строгая валидация (`type ∈ TicketType`,
    форма slug) — на границе API в CRUD (#126).
    """

    __tablename__ = "canned_responses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    linked_article_slug: Mapped[str | None] = mapped_column(String(512), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<CannedResponse id={self.id!r} title={self.title!r}>"
