"""init

Empty initial migration — anchor head.

Создаёт пустую базу. Все реальные таблицы (tickets, ticket_messages,
ticket_history, ...) появятся в последующих миграциях E1 Issues #5+.

Revision ID: 20260530_120000_init
Revises:
Create Date: 2026-05-30 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260530_120000_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
