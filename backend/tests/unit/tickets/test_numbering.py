"""Unit-тесты формата номера заявки (без БД)."""

from __future__ import annotations

from api.tickets.numbering import format_ticket_number


def test_format_pads_to_five_digits() -> None:
    assert format_ticket_number(2026, 42) == "RH-2026-00042"


def test_format_first() -> None:
    assert format_ticket_number(2027, 1) == "RH-2027-00001"


def test_format_does_not_truncate_large_n() -> None:
    assert format_ticket_number(2026, 123456) == "RH-2026-123456"
