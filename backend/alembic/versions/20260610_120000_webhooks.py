"""webhooks: таблица webhook_subscriptions (подписки на исходящие события)

E10-8 PR-A (#198, ADR-0015 D2). Создаёт `webhook_subscriptions` — конфиг внешней
доставки: url подписчика, events (JSONB-массив имён), secret (HMAC D3), is_active.

Рукописная миграция. `events` — JSONB (массив строк-имён событий). `url` — внешний адрес
подписчика, БЕЗ FK (арх-константа: не ссылка на таблицу). `secret` — во внутреннем контуре.

Revision ID: 20260610_120000_webhooks
Revises: 20260608_120000_claims
Create Date: 2026-06-10 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260610_120000_webhooks"
down_revision: str | None = "20260608_120000_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret", sa.String(length=256), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_subscriptions"),
    )


def downgrade() -> None:
    op.drop_table("webhook_subscriptions")
