"""Unit-тесты cursor-пагинации и sort-спеков (без БД)."""

from __future__ import annotations

import base64
import uuid

import pytest

from api.tickets.pagination import (
    _PRIORITY_RANK,
    DEFAULT_SORT,
    decode_cursor,
    encode_cursor,
    get_sort_spec,
)


def test_cursor_roundtrip_datetime_value() -> None:
    ticket_id = uuid.uuid4()
    value = "2026-05-30T12:00:00+00:00"
    decoded_value, decoded_id = decode_cursor(encode_cursor(value, ticket_id))
    assert decoded_value == value
    assert decoded_id == ticket_id


def test_cursor_roundtrip_int_value() -> None:
    ticket_id = uuid.uuid4()
    decoded_value, decoded_id = decode_cursor(encode_cursor(3, ticket_id))
    assert decoded_value == 3
    assert decoded_id == ticket_id


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "%%% not base64 %%%",
        base64.urlsafe_b64encode(b"not json").decode(),
        base64.urlsafe_b64encode(b'{"v": 1}').decode(),  # нет id
        base64.urlsafe_b64encode(b'{"v": 1, "id": "not-a-uuid"}').decode(),
    ],
)
def test_decode_invalid_cursor_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        decode_cursor(bad)


def test_cursor_is_opaque_base64() -> None:
    cursor = encode_cursor("2026-05-30T12:00:00+00:00", uuid.uuid4())
    # Раскодируется обратно в JSON — значит это base64, а не plaintext.
    assert base64.urlsafe_b64decode(cursor.encode()).startswith(b"{")


def test_get_sort_spec_defaults_on_none_and_unknown() -> None:
    assert get_sort_spec(None) == get_sort_spec(DEFAULT_SORT)
    assert get_sort_spec("nonsense") == get_sort_spec(DEFAULT_SORT)


def test_sort_spec_fields_and_directions() -> None:
    assert get_sort_spec("created_at").descending is False
    assert get_sort_spec("-created_at").descending is True
    assert get_sort_spec("resolution_due_at").field == "resolution_due_at"
    assert get_sort_spec("priority").field == "priority"
    assert get_sort_spec("-priority").descending is True


def test_priority_rank_is_semantic_not_alphabetical() -> None:
    assert (
        _PRIORITY_RANK["low"]
        < _PRIORITY_RANK["normal"]
        < _PRIORITY_RANK["high"]
        < _PRIORITY_RANK["critical"]
    )
