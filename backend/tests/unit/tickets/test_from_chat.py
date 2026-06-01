"""Unit-тесты логики приёма эскалации из чата (E3-1, #69) без БД.

Покрывают чистые хелперы `_derive_subject_from_transcript` / `_chat_custom_fields`
и валидацию схемы `TicketFromChat`. Полный путь endpoint'а (201/дедуп/403/422) —
в integration-тестах (требуют Postgres)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from api.tickets.repository import (
    _CHAT_SUBJECT_FALLBACK,
    _chat_custom_fields,
    _derive_subject_from_transcript,
)
from api.tickets.schemas import TicketFromChat, TranscriptTurn


def _payload(**extra: object) -> TicketFromChat:
    base: dict[str, object] = {
        "chat_session_id": uuid.uuid4(),
        "requester_id": uuid.uuid4(),
    }
    base.update(extra)
    return TicketFromChat.model_validate(base)


def test_subject_from_explicit_is_not_derived() -> None:
    # Если subject задан — деривация не вызывается (проверяем сам дериватор отдельно).
    payload = _payload(subject="Явная тема")
    assert payload.subject == "Явная тема"


def test_derive_subject_takes_first_user_turn() -> None:
    payload = _payload(
        transcript=[
            {"role": "assistant", "content": "Здравствуйте! Чем помочь?"},
            {"role": "user", "content": "  Не приходит чек об оплате  "},
            {"role": "user", "content": "Второе сообщение"},
        ]
    )
    assert _derive_subject_from_transcript(payload) == "Не приходит чек об оплате"


def test_derive_subject_trims_to_300() -> None:
    long = "ы" * 500
    payload = _payload(transcript=[{"role": "user", "content": long}])
    assert len(_derive_subject_from_transcript(payload)) == 300


def test_derive_subject_fallback_when_no_user_turn() -> None:
    payload = _payload(transcript=[{"role": "assistant", "content": "только бот"}])
    assert _derive_subject_from_transcript(payload) == _CHAT_SUBJECT_FALLBACK


def test_derive_subject_fallback_when_no_transcript() -> None:
    assert _derive_subject_from_transcript(_payload()) == _CHAT_SUBJECT_FALLBACK


def test_chat_custom_fields_serialises_transcript() -> None:
    payload = _payload(
        transcript=[{"role": "user", "content": "вопрос", "at": "2026-06-01T09:00:00Z"}]
    )
    cf = _chat_custom_fields(payload)
    assert cf["chat_transcript"][0]["role"] == "user"
    assert cf["chat_transcript"][0]["content"] == "вопрос"
    # at сериализуется в JSON-совместимую строку.
    assert isinstance(cf["chat_transcript"][0]["at"], str)


def test_chat_custom_fields_empty_without_transcript() -> None:
    assert _chat_custom_fields(_payload()) == {}


def test_schema_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        TicketFromChat.model_validate(
            {"chat_session_id": uuid.uuid4(), "requester_id": uuid.uuid4(), "bogus": 1}
        )


def test_schema_requires_chat_session_and_requester() -> None:
    with pytest.raises(ValidationError):
        TicketFromChat.model_validate({"chat_session_id": uuid.uuid4()})


def test_transcript_turn_rejects_bad_role() -> None:
    with pytest.raises(ValidationError):
        TranscriptTurn.model_validate({"role": "system", "content": "x"})
