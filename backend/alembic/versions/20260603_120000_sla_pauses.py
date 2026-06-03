"""sla pause accounting: tickets.sla_paused_at + sla_paused_seconds

Добавляет учёт пауз SLA (E4-4 #88, FR-4.5 / ADR-0007 Решение 2: паузы = PENDING+WAITING):
`sla_paused_at` (начало текущей паузы, nullable) и `sla_paused_seconds` (накопленная
длительность, NOT NULL server_default 0 — для существующих строк). Только своя таблица
tickets (арх-константа).

Revision ID: 20260603_120000_sla_pauses
Revises: 20260602_120000_sla_tables
Create Date: 2026-06-03 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260603_120000_sla_pauses"
down_revision: str | None = "20260602_120000_sla_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("sla_paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "sla_paused_seconds",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tickets", "sla_paused_seconds")
    op.drop_column("tickets", "sla_paused_at")
