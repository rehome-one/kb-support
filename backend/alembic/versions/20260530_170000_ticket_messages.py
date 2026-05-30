"""ticket messages table

Создаёт таблицу `ticket_messages` — переписка по заявке (ТЗ §3.5). `ticket_id` —
FK на собственную `tickets`. Инвариант NFR-1.3 (скрытие is_internal от заявителя)
обеспечивается на уровне запроса (`TicketMessageRepository.list_for_principal`).

Revision ID: 20260530_170000_ticket_messages
Revises: 20260530_160000_ticket_history
Create Date: 2026-05-30 17:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260530_170000_ticket_messages"
down_revision: str | None = "20260530_160000_ticket_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("author_type", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name="fk_ticket_messages_ticket_id"),
    )
    op.create_index(
        "ix_ticket_messages_ticket_id_created_at",
        "ticket_messages",
        ["ticket_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_messages_ticket_id_created_at", table_name="ticket_messages")
    op.drop_table("ticket_messages")
