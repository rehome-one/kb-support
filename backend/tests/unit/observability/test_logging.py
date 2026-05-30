"""Unit-тесты JSON-логирования (поля + маскирование ПДн)."""

from __future__ import annotations

import json
import logging

from api.observability.context import actor_sub_var, request_id_var
from api.observability.logging import JsonFormatter


def _record(msg: str, *, level: int = logging.INFO, name: str = "api.test") -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, (), None)


def test_json_has_required_fields() -> None:
    data = json.loads(JsonFormatter().format(_record("ticket created")))
    assert {"ts", "level", "event", "logger", "request_id", "actor_sub"} <= set(data)
    assert data["level"] == "INFO"
    assert data["event"] == "ticket created"
    assert data["logger"] == "api.test"


def test_pii_masked_in_event() -> None:
    data = json.loads(JsonFormatter().format(_record("requester email john@example.com")))
    assert "john@example.com" not in data["event"]
    assert "***" in data["event"]


def test_request_id_and_actor_from_context() -> None:
    rid_token = request_id_var.set("rid-1")
    sub_token = actor_sub_var.set("sub-9")
    try:
        data = json.loads(JsonFormatter().format(_record("x")))
        assert data["request_id"] == "rid-1"
        assert data["actor_sub"] == "sub-9"
    finally:
        request_id_var.reset(rid_token)
        actor_sub_var.reset(sub_token)


def test_context_defaults_to_null() -> None:
    data = json.loads(JsonFormatter().format(_record("x")))
    assert data["request_id"] is None
    assert data["actor_sub"] is None


def test_exception_trace_present_and_masked() -> None:
    """NFR-1.5: ПДн в трейсе исключения тоже маскируются."""
    import sys

    try:
        raise ValueError("leaked secret@example.com")
    except ValueError:
        record = logging.LogRecord(
            "api.test", logging.ERROR, __file__, 1, "boom", (), sys.exc_info()
        )
    data = json.loads(JsonFormatter().format(record))
    assert "exc" in data
    assert "secret@example.com" not in data["exc"]
    assert "***" in data["exc"]


def test_bind_actor_sub_sets_context() -> None:
    from api.observability.context import bind_actor_sub, get_actor_sub

    token = actor_sub_var.set(None)
    try:
        bind_actor_sub("operator-1")
        assert get_actor_sub() == "operator-1"
    finally:
        actor_sub_var.reset(token)
