"""sla tables: business_hours + sla_policies + FK tickets.sla_policy_id

Создаёт таблицы `business_hours` и `sla_policies` (ТЗ §3.8, ADR-0007, E4-1 #85) и
добавляет FK `tickets.sla_policy_id → sla_policies.id` (ON DELETE SET NULL) —
выполняет обещание из комментария модели Ticket («станет FK на sla_policies в E4»).

Рукописная миграция (не autogenerate). Перечисления — VARCHAR (Issue #5, ADR-0007),
нативные PG ENUM не создаются. FK только к СВОИМ таблицам (арх-константа).

Порядок upgrade: business_hours → sla_policies (FK на неё) → FK на tickets.
Порядок downgrade — зеркальный: снять FK с tickets → drop sla_policies → drop business_hours.

Revision ID: 20260602_120000_sla_tables
Revises: 20260601_120000_chat_uniq
Create Date: 2026-06-02 12:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260602_120000_sla_tables"
down_revision: str | None = "20260601_120000_chat_uniq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_TICKETS_SLA = "fk_tickets_sla_policy_id"


def upgrade() -> None:
    # 1) business_hours (на неё ссылается sla_policies).
    op.create_table(
        "business_hours",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "schedule",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_business_hours"),
    )

    # 2) sla_policies (FK на business_hours, ON DELETE SET NULL → 24/7 при удалении графика).
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "applies_to",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("first_response_minutes", sa.Integer(), nullable=False),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False),
        sa.Column("business_hours_id", sa.Uuid(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_sla_policies"),
        sa.ForeignKeyConstraint(
            ["business_hours_id"],
            ["business_hours.id"],
            name="fk_sla_policies_business_hours_id",
            ondelete="SET NULL",
        ),
    )

    # 3) FK tickets.sla_policy_id → sla_policies.id (колонка уже есть с E1, добавляем констрейнт).
    op.create_foreign_key(
        _FK_TICKETS_SLA,
        "tickets",
        "sla_policies",
        ["sla_policy_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Зеркально: сначала снять FK с tickets (таблица tickets не удаляется), затем
    # удалить sla_policies, затем business_hours.
    op.drop_constraint(_FK_TICKETS_SLA, "tickets", type_="foreignkey")
    # Колонка tickets.sla_policy_id появилась в E1 и переживает откат, но ссылки на
    # удаляемую sla_policies без неё бессмысленны — обнуляем, иначе повторный upgrade
    # не сможет вернуть FK (висячие значения нарушат констрейнт). С E4-3 (#87) заявки
    # реально несут sla_policy_id, поэтому очистка обязательна для идемпотентности up/down.
    op.execute("UPDATE tickets SET sla_policy_id = NULL")
    op.drop_table("sla_policies")
    op.drop_table("business_hours")
