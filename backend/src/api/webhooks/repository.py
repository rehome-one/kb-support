"""Репозиторий webhook-подписок (E10-8 PR-A #198).

Контракт даёт только `GET /webhooks` (список) и `POST /webhooks` (создание) — без
get-by-id/patch/delete, поэтому здесь только `list`/`create`. `list_active_for_event`
(выбор подписок под конкретное событие при доставке) добавит PR-B. Commit — на стороне
роутера (паттерн `CannedResponseRepository`/`SLAPolicyRepository`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.webhooks.models import WebhookSubscription


class WebhookSubscriptionRepository:
    """Чтение/создание webhook-подписок поверх `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> Sequence[WebhookSubscription]:
        """Все подписки, детерминированный порядок (`created_at desc, id`)."""
        stmt = select(WebhookSubscription).order_by(
            WebhookSubscription.created_at.desc(), WebhookSubscription.id
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def list_active_for_event(self, event: str) -> Sequence[WebhookSubscription]:
        """Активные подписки, чьи `events` содержат `event` (JSONB `@>`). Для доставки PR-B."""
        stmt = (
            select(WebhookSubscription)
            .where(
                WebhookSubscription.is_active.is_(True),
                WebhookSubscription.events.contains([event]),
            )
            .order_by(WebhookSubscription.created_at.desc(), WebhookSubscription.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def create(self, values: dict[str, Any]) -> WebhookSubscription:
        """Создать подписку из готовых значений колонок (валидация — в схеме/роутере)."""
        subscription = WebhookSubscription(**values)
        self._session.add(subscription)
        await self._session.flush()
        return subscription
