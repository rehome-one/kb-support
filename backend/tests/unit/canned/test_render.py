"""Unit-тесты подстановки переменных шаблона (E6-3 #127) — чистые, без I/O.

Покрывают: подстановку известных переменных; **неизвестные/недоступные токены остаются
как `{{var}}`** (плейсхолдер); пробелы в токене; build_local_variables из заявки.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

from api.canned.render import build_local_variables, render_template


def test_substitutes_known_variables() -> None:
    body = "Здравствуйте, {{requester_name}}! Заявка {{ticket_number}}."
    out = render_template(body, {"requester_name": "Иван", "ticket_number": "TCK-1"})
    assert out == "Здравствуйте, Иван! Заявка TCK-1."


def test_unknown_token_left_as_is() -> None:
    # Недоступная переменная (напр. requester_name до #77) остаётся плейсхолдером.
    body = "Привет, {{requester_name}}! Номер {{ticket_number}}."
    out = render_template(body, {"ticket_number": "TCK-2"})
    assert out == "Привет, {{requester_name}}! Номер TCK-2."


def test_whitespace_in_token() -> None:
    assert render_template("{{  ticket_number  }}", {"ticket_number": "X"}) == "X"


def test_no_eval_no_logic() -> None:
    # Не шаблонизатор-движок: выражения/доступ к атрибутам НЕ исполняются (нет SSTI).
    body = "{{ticket.subject}} {{1+1}} {{__import__}}"
    # точечный/числовой/dunder токены не матчат [a-zA-Z_]\w* целиком → остаются как есть
    assert render_template(body, {"ticket": "x"}) == body


def test_build_local_variables() -> None:
    ticket: Any = SimpleNamespace(number="TCK-9", subject="тема", type="FRAUD")
    today = datetime.date(2026, 6, 6)
    variables = build_local_variables(ticket, today=today)
    assert variables == {
        "ticket_number": "TCK-9",
        "ticket_subject": "тема",
        "ticket_type": "FRAUD",
        "current_date": "2026-06-06",
    }
