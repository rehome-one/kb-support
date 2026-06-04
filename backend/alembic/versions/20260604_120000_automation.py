"""automation_rules: правила автоматизации (ТЗ §3.9, ADR-0008, E5-1 #103)

Создаёт таблицу `automation_rules` (trigger→conditions→actions, `apply_order`,
`is_active`) + индекс под запрос матчера (#105). Рукописная миграция (не autogenerate).
Перечисление `trigger` — VARCHAR (Issue #5, ADR-0008), нативный PG ENUM не создаётся.
**Без FK** — таблица самостоятельна (арх-константа: ни к чужим БД, ни к своим).

Revision ID: 20260604_120000_automation
Revises: 20260603_120000_sla_pauses
Create Date: 2026-06-04 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260604_120000_automation"
down_revision: str | None = "20260603_120000_sla_pauses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_automation_rules_trigger_active_apply_order"


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("apply_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
    op.create_index(_INDEX, "automation_rules", ["trigger", "is_active", "apply_order"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="automation_rules")
    op.drop_table("automation_rules")
