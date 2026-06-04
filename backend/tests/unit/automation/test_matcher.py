"""Unit-тесты матчера условий автоматизации (E5-3 #105) — чистые, без БД.

Покрывают: измерения type/priority/channel (membership + wildcard), конъюнкцию
(в т.ч. fail по keywords), keywords (ci/substring/any/wildcard/защита от не-строк,
матч по description И subject), пустой conditions=catch-all, select_matching_rules
(несколько в порядке + фильтр).
"""

from __future__ import annotations

from typing import Any

from api.automation.matcher import conditions_match, select_matching_rules
from api.automation.models import AutomationRule


def _match(conditions: dict[str, Any], **over: str) -> bool:
    base = {
        "ticket_type": "FRAUD",
        "ticket_priority": "critical",
        "ticket_channel": "AI_CHAT",
        "ticket_text": "тема заявки\nописание заявки",
    }
    base.update(over)
    return conditions_match(conditions, **base)


def _rule(conditions: dict[str, Any], name: str = "r") -> AutomationRule:
    return AutomationRule(name=name, trigger="on_create", conditions=conditions, actions=[])


# --- измерения + wildcard ---


def test_empty_conditions_is_catch_all() -> None:
    assert _match({}) is True


def test_type_membership_and_mismatch() -> None:
    assert _match({"types": ["FRAUD", "PAYMENT"]}) is True
    assert _match({"types": ["PAYMENT"]}) is False


def test_priority_and_channel_dimensions() -> None:
    assert _match({"priorities": ["critical"]}) is True
    assert _match({"priorities": ["low"]}) is False
    assert _match({"channels": ["AI_CHAT"]}) is True
    assert _match({"channels": ["EMAIL"]}) is False


def test_empty_or_missing_dimension_is_wildcard() -> None:
    assert _match({"types": []}) is True  # пустой список = wildcard
    assert _match({"priorities": []}) is True


# --- конъюнкция ---


def test_conjunction_all_must_pass() -> None:
    assert _match({"types": ["FRAUD"], "priorities": ["critical"]}) is True
    # одно измерение не совпало → всё правило не матчится
    assert _match({"types": ["FRAUD"], "priorities": ["low"]}) is False


def test_conjunction_fails_on_keywords() -> None:
    assert _match({"types": ["FRAUD"], "keywords": ["отсутствует"]}) is False
    assert _match({"types": ["FRAUD"], "keywords": ["описание"]}) is True


# --- keywords ---


def test_keyword_substring_case_insensitive() -> None:
    # частичное слово, другой регистр → матч (substring, ci)
    assert _match({"keywords": ["ОПИСАН"]}) is True


def test_keyword_any_of_list() -> None:
    assert _match({"keywords": ["нетакого", "тема"]}) is True  # одно совпало → матч


def test_keyword_matches_description_not_subject() -> None:
    text = "тема про оплату\nтело про возврат"
    assert _match({"keywords": ["возврат"]}, ticket_text=text) is True  # только в description
    assert _match({"keywords": ["оплату"]}, ticket_text=text) is True  # только в subject
    assert _match({"keywords": ["залог"]}, ticket_text=text) is False  # нигде


def test_keyword_empty_or_missing_is_wildcard() -> None:
    assert _match({"keywords": []}) is True
    assert _match({}) is True


def test_keyword_non_string_elements_skipped() -> None:
    # Защита: мусорный элемент пропускается, валидные слова продолжают работать.
    assert _match({"keywords": ["описание", 123]}) is True
    assert _match({"keywords": [123, 456]}) is False  # ни одного валидного совпадения


# --- select_matching_rules ---


def test_select_returns_matching_in_order() -> None:
    rules = [
        _rule({"types": ["FRAUD"]}, "a"),  # матч
        _rule({"types": ["PAYMENT"]}, "b"),  # не матч
        _rule({}, "c"),  # catch-all → матч
    ]
    selected = select_matching_rules(
        rules,
        ticket_type="FRAUD",
        ticket_priority="critical",
        ticket_channel="AI_CHAT",
        ticket_text="t\nd",
    )
    assert [r.name for r in selected] == ["a", "c"]


def test_select_empty_input() -> None:
    assert (
        select_matching_rules(
            [],
            ticket_type="FRAUD",
            ticket_priority="critical",
            ticket_channel="AI_CHAT",
            ticket_text="t",
        )
        == []
    )
