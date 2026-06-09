"""ORM-модель webhook-подписки `WebhookSubscription` (E10-8 PR-A #198; ADR-0015 D2).

Конфиг внешней доставки: `url` подписчика, `events` (JSONB-массив имён, домен
`WebhookEvent`, валидация на границе API), `secret` (HMAC-секрет подписи D3), `is_active`.

**ФЗ-152 / ADR-0015 У6:** `secret` НЕ отдаётся в list/get-ответах и НЕ логируется
(`__repr__` его не включает); хранится в СВОЕЙ БД (внутренний контур). Без FK к чужим БД
(арх-константа): `url` — внешний адрес подписчика, не ссылка на нашу/чужую таблицу.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, TimestampMixin


class WebhookSubscription(TimestampMixin, Base):
    """Подписка внешнего потребителя на webhook-события (контракт `WebhookSubscription`)."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    secret: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    def __repr__(self) -> str:
        # secret НАМЕРЕННО не включён (ФЗ-152, ADR-0015 У6).
        return f"<WebhookSubscription id={self.id!r} url={self.url!r} active={self.is_active!r}>"
