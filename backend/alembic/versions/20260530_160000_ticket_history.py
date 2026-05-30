"""ticket history table

Создаёт таблицу `ticket_history` — неизменяемый журнал действий по заявке
(ТЗ §3.7, NFR-1.4, ФЗ-152). `ticket_id` — FK на собственную таблицу `tickets`
(внутрисервисная целостность; арх-константа запрещает FK только к чужим БД).

Revision ID: 20260530_160000_ticket_history
Revises: 20260530_150000_ticket_num_seq
Create Date: 2026-05-30 16:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260530_160000_ticket_history"
down_revision: str | None = "20260530_150000_ticket_num_seq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("to_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name="fk_ticket_history_ticket_id"),
    )
    op.create_index(
        "ix_ticket_history_ticket_id_created_at",
        "ticket_history",
        ["ticket_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_history_ticket_id_created_at", table_name="ticket_history")
    op.drop_table("ticket_history")
