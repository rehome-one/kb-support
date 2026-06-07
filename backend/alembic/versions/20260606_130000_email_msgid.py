"""ticket_messages.email_message_id + частичный uniq (идемпотентность email-приёма)

Дедуп входящих писем по Message-ID (E7-3, #145): повторно доставленное письмо не
создаёт дубль. Носитель дедупа — сообщение (покрывает и новое письмо, и ответ
единообразно). Частичный uniq только для строк с email_message_id IS NOT NULL —
не-email сообщения не затрагиваются.

Revision ID: 20260606_130000_email_msgid
Revises: 20260606_120000_canned
Create Date: 2026-06-06 13:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260606_130000_email_msgid"
down_revision: str | None = "20260606_120000_canned"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ticket_messages",
        sa.Column("email_message_id", sa.String(length=998), nullable=True),
    )
    op.create_index(
        "uq_ticket_messages_email_message_id",
        "ticket_messages",
        ["email_message_id"],
        unique=True,
        postgresql_where=sa.text("email_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ticket_messages_email_message_id", table_name="ticket_messages")
    op.drop_column("ticket_messages", "email_message_id")
