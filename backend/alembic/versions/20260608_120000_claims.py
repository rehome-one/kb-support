"""claims: 12 полей претензионных типов на tickets + таблица ticket_case_details

E10-1 (#191, §3.1.1/§3.11, ADR-0013 D4). Добавляет 12 nullable claims-колонок на
`tickets` и создаёт `ticket_case_details` (1:1 к tickets, ON DELETE CASCADE).

Рукописная миграция. Суммы — NUMERIC(14,2) (точное хранение; kb-support деньги не считает,
FR-9.8). Перечисления — VARCHAR (Issue #5). Ссылки на upstream (*_id) — UUID БЕЗ FK
(арх-константа; разрешаются по сети). FK ticket_id → tickets.id — к СВОЕЙ таблице.

Revision ID: 20260608_120000_claims
Revises: 20260606_130000_email_msgid
Create Date: 2026-06-08 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260608_120000_claims"
down_revision: str | None = "20260606_130000_email_msgid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLAIMS_COLUMNS = (
    ("case_state", sa.String(length=32)),
    ("claim_amount", sa.Numeric(14, 2)),
    ("approved_amount", sa.Numeric(14, 2)),
    ("decision", sa.String(length=16)),
    ("decision_reason", sa.Text()),
    ("decision_notified_at", sa.DateTime(timezone=True)),
    ("payout_due_at", sa.DateTime(timezone=True)),
    ("linked_payment_id", sa.Uuid()),
    ("regress_obligation_id", sa.Uuid()),
    ("policy_id", sa.Uuid()),
    ("insurance_event_id", sa.Uuid()),
    ("acceptance_act_id", sa.Uuid()),
)


def upgrade() -> None:
    # 1) 12 claims-колонок на tickets (все nullable — заполнены только у claims-типов).
    for name, col_type in _CLAIMS_COLUMNS:
        op.add_column("tickets", sa.Column(name, col_type, nullable=True))

    # 2) ticket_case_details — 1:1 к tickets (FK ON DELETE CASCADE, unique ticket_id).
    op.create_table(
        "ticket_case_details",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("act_kind", sa.String(length=16), nullable=True),
        sa.Column("signing_status", sa.String(length=16), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
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
        sa.PrimaryKeyConstraint("id", name="pk_ticket_case_details"),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="fk_ticket_case_details_ticket_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("ticket_id", name="uq_ticket_case_details_ticket_id"),
    )


def downgrade() -> None:
    # Зеркально: drop таблицы деталей, затем claims-колонки tickets.
    op.drop_table("ticket_case_details")
    for name, _ in reversed(_CLAIMS_COLUMNS):
        op.drop_column("tickets", name)
