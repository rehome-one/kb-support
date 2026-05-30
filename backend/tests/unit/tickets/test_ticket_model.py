"""Структурные unit-тесты ORM-модели Ticket (без подключения к БД).

Проверяют схему таблицы из `Ticket.__table__`: имена/обязательность колонок,
индексы, unique-ограничение и — критично — отсутствие любых ForeignKey
(архитектурная константа §3.10: ссылки на чужие сущности только по UUID).
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import ColumnDefault, Index, Table, UniqueConstraint

from api.tickets.models import Ticket

# `Model.__table__` типизирован как FromClause; для доступа к .indexes /
# .constraints / .primary_key приводим к Table.
TABLE: Table = cast(Table, Ticket.__table__)

ALL_COLUMNS = {
    "id",
    "number",
    "subject",
    "description",
    "status",
    "priority",
    "type",
    "channel",
    "team",
    "access_level",
    "requester_id",
    "assignee_id",
    "premises_id",
    "booking_id",
    "collaborator_id",
    "service_order_id",
    "chat_session_id",
    "sla_policy_id",
    "first_response_due_at",
    "resolution_due_at",
    "first_responded_at",
    "resolved_at",
    "closed_at",
    "reopened_count",
    "tags",
    "custom_fields",
    "rating",
    "rating_comment",
    "created_at",
    "updated_at",
}

REFERENCE_ID_COLUMNS = {
    "requester_id",
    "assignee_id",
    "premises_id",
    "booking_id",
    "collaborator_id",
    "service_order_id",
    "chat_session_id",
    "sla_policy_id",
}

NOT_NULL_COLUMNS = {
    "id",
    "number",
    "subject",
    "description",
    "status",
    "priority",
    "type",
    "channel",
    "access_level",
    "requester_id",
    "reopened_count",
    "tags",
    "custom_fields",
    "created_at",
    "updated_at",
}


def test_tablename() -> None:
    assert Ticket.__tablename__ == "tickets"


def test_has_exactly_expected_columns() -> None:
    """Полнота охвата §3.1 — ни лишних, ни недостающих колонок.

    Поля §3.1.1 (claims) сознательно отсутствуют — это E10.
    """
    assert set(TABLE.columns.keys()) == ALL_COLUMNS


def test_claims_fields_absent() -> None:
    """Поля претензионных типов (§3.1.1) не должны появиться раньше E10."""
    cols = set(TABLE.columns.keys())
    claims = {
        "case_state",
        "claim_amount",
        "approved_amount",
        "decision",
        "decision_reason",
        "linked_payment_id",
        "policy_id",
        "insurance_event_id",
        "acceptance_act_id",
    }
    assert cols.isdisjoint(claims)


def test_not_null_columns() -> None:
    cols = TABLE.columns
    for name in NOT_NULL_COLUMNS:
        assert cols[name].nullable is False, f"{name} должна быть NOT NULL"


def test_nullable_columns() -> None:
    cols = TABLE.columns
    for name in ALL_COLUMNS - NOT_NULL_COLUMNS:
        assert cols[name].nullable is True, f"{name} должна быть nullable"


def test_no_foreign_keys_arch_constant() -> None:
    """Арх-константа §3.10: НИ ОДНОГО ForeignKey — чужие сущности только по UUID."""
    assert TABLE.foreign_keys == set()
    for name in REFERENCE_ID_COLUMNS:
        assert TABLE.columns[name].foreign_keys == set()


def test_primary_key_is_id() -> None:
    assert [c.name for c in TABLE.primary_key.columns] == ["id"]


def test_number_unique_constraint() -> None:
    unique = [c for c in TABLE.constraints if isinstance(c, UniqueConstraint)]
    assert any(
        [col.name for col in c.columns] == ["number"] and c.name == "uq_tickets_number"
        for c in unique
    )


def test_expected_indexes() -> None:
    index_map = {str(ix.name): [c.name for c in ix.columns] for ix in TABLE.indexes}
    assert index_map.get("ix_tickets_requester_id") == ["requester_id"]
    assert index_map.get("ix_tickets_assignee_id") == ["assignee_id"]
    assert index_map.get("ix_tickets_status_created_at") == ["status", "created_at"]


def _scalar_default(col_name: str) -> object:
    """Аргумент Python-side скалярного дефолта колонки (ColumnDefault.arg)."""
    default = TABLE.columns[col_name].default
    assert isinstance(default, ColumnDefault)
    return default.arg


def test_column_defaults() -> None:
    """Python-side дефолты заданы для status/priority/access_level/счётчиков."""
    assert _scalar_default("status") == "NEW"
    assert _scalar_default("priority") == "normal"
    assert _scalar_default("access_level") == "LOGGED"
    assert _scalar_default("reopened_count") == 0


def test_isinstance_index_type() -> None:
    """Sanity: __table_args__ действительно создал объекты Index."""
    assert all(isinstance(ix, Index) for ix in TABLE.indexes)


def test_repr_contains_key_fields() -> None:
    """__repr__ включает id / number / status (без чувствительных полей)."""
    ticket = Ticket(number="RH-2026-00001", status="NEW")
    rendered = repr(ticket)
    assert "RH-2026-00001" in rendered
    assert "NEW" in rendered
    assert rendered.startswith("<Ticket ")
