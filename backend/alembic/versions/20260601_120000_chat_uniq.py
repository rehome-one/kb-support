"""partial unique index on tickets.chat_session_id (active tickets)

Идемпотентность эскалации из AI-чата (E3-1, #69): не более одной АКТИВНОЙ
(status <> 'CLOSED') заявки на chat_session_id. Re-эскалация после закрытия
разрешена. Частичный uniq защищает от гонки параллельных эскалаций и служит
быстрым lookup'ом для дедупа. Только для строк с chat_session_id IS NOT NULL
(не-чатовые заявки не затрагиваются).

Revision ID: 20260601_120000_chat_uniq
Revises: 20260530_170000_ticket_messages
Create Date: 2026-06-01 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260601_120000_chat_uniq"
down_revision: str | None = "20260530_170000_ticket_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_tickets_active_chat_session",
        "tickets",
        ["chat_session_id"],
        unique=True,
        postgresql_where="chat_session_id IS NOT NULL AND status <> 'CLOSED'",
    )


def downgrade() -> None:
    op.drop_index("uq_tickets_active_chat_session", table_name="tickets")
