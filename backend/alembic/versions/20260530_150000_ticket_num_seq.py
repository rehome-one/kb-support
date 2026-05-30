"""ticket number sequence

Создаёт PostgreSQL-sequence `ticket_number_seq` для генерации номеров заявок
`RH-YYYY-NNNNN` (см. `api.tickets.numbering`). Конкуррентно-безопасный источник
порядкового N; уникальность номера дополнительно защищена unique-constraint
`uq_tickets_number` (#5).

Revision ID: 20260530_150000_ticket_num_seq
Revises: 20260530_140000_tickets_table
Create Date: 2026-05-30 15:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260530_150000_ticket_num_seq"
down_revision: str | None = "20260530_140000_tickets_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS ticket_number_seq START WITH 1 INCREMENT BY 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS ticket_number_seq")
