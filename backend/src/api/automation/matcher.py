"""Матчинг условий правил автоматизации (E5-3 #105, ТЗ §3.9; ADR-0008 Реш.1/2).

Чистые функции без I/O: на вход — уже загруженные активные правила нужного триггера
(порядок `apply_order asc, id` из `AutomationRuleRepository.list_active(trigger)`), на
выход — список ВСЕХ подходящих в том же порядке. В отличие от SLA (одна политика,
`select_policy`→first), к заявке применяется НЕСКОЛЬКО правил — порядок `apply_order`,
конфликт = last-write-wins на исполнении (#107, ADR-0008 Реш.7).

**Матчинг** — конъюнкция измерений `conditions`; отсутствующее/пустое измерение =
wildcard; пустой `conditions={}` = catch-all (ADR-0008 Реш.1). Сравнение по строковым
значениям доменных enum (в БД хранятся как `.value`). `conditions` читается защитно
(сырой JSONB-dict, не полагаемся на прохождение через Pydantic — паттерн `sla/matcher`).

**`ticket_text`** (контракт границы) — объединённый текст заявки `subject + "\n" +
description`, по которому идёт keyword-поиск (ADR-0008 Реш.2: substring, case-insensitive,
ЛЮБОЕ слово из списка). Композицию выполняет вызывающий (#107); матчер только ищет.

**`select_matching_rules`** ожидает правила, УЖЕ отфильтрованные по триггеру
(`list_active(trigger)`) — фильтрация по `trigger` не дублируется здесь (поэтому, в
отличие от формулировки тела Issue, параметра `trigger` у матчера нет).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from api.automation.models import AutomationRule


def _dimension_ok(values: object, ticket_value: str) -> bool:
    """Измерение `conditions` — wildcard (отсутствует/не-список/пусто) или содержит значение."""
    if not isinstance(values, list) or not values:
        return True
    return ticket_value in values


def _keywords_ok(keywords: object, ticket_text: str) -> bool:
    """keywords — wildcard (пусто/отсутствует/не-список) или ЛЮБОЕ слово — подстрока
    `ticket_text` без учёта регистра (ADR-0008 Реш.2). Не-строковые элементы списка
    пропускаются (защита от мусора в сыром JSONB), валидные продолжают работать."""
    if not isinstance(keywords, list) or not keywords:
        return True
    text = ticket_text.casefold()
    return any(isinstance(word, str) and word.casefold() in text for word in keywords)


def conditions_match(
    conditions: Mapping[str, object],
    *,
    ticket_type: str,
    ticket_priority: str,
    ticket_channel: str,
    ticket_text: str,
) -> bool:
    """Подходит ли заявка под `conditions` (конъюнкция; пустой `{}` = catch-all)."""
    return (
        _dimension_ok(conditions.get("types"), ticket_type)
        and _dimension_ok(conditions.get("priorities"), ticket_priority)
        and _dimension_ok(conditions.get("channels"), ticket_channel)
        and _keywords_ok(conditions.get("keywords"), ticket_text)
    )


def select_matching_rules(
    rules: Sequence[AutomationRule],
    *,
    ticket_type: str,
    ticket_priority: str,
    ticket_channel: str,
    ticket_text: str,
) -> list[AutomationRule]:
    """Все правила, чьи `conditions` подходят заявке, в исходном порядке (apply_order).

    `rules` ожидаются уже отфильтрованными по триггеру и отсортированными
    (`list_active(trigger)`: `apply_order asc, id`) — порядок сохраняется для #107.
    """
    return [
        rule
        for rule in rules
        if conditions_match(
            rule.conditions,
            ticket_type=ticket_type,
            ticket_priority=ticket_priority,
            ticket_channel=ticket_channel,
            ticket_text=ticket_text,
        )
    ]
