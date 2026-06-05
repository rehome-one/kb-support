"""canned_responses: шаблоны ответов (§3.6 ТЗ, ADR-0009, E6-1 #125)

Создаёт таблицу `canned_responses` (title/body/type/linked_article_slug/usage_count).
Рукописная миграция (не autogenerate). `type` — VARCHAR (Issue #5, без нативного PG
ENUM). **Без FK** (арх-константа): `linked_article_slug` — строка, существование статьи
проверяет HTTP-клиент kb-wiki (#129), не БД.

Revision ID: 20260606_120000_canned
Revises: 20260604_120000_automation
Create Date: 2026-06-06 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260606_120000_canned"
down_revision: str | None = "20260604_120000_automation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canned_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=True),
        sa.Column("linked_article_slug", sa.String(length=512), nullable=True),
        sa.Column("usage_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("canned_responses")
