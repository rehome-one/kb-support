"""Anti-drift тесты доменных перечислений Ticket против OpenAPI-контракта.

Контракт `docs/handoff/01_postanovka/04_openapi.yaml` — immutable источник
правды домена (Issue #5). Если значения Python-энумов разойдутся с контрактом —
тест падает. Это страховка перед production-spec (#11).

YAML-зависимости избегаем намеренно (pyyaml не в deps) — извлекаем enum-блоки
лёгким парсером, повторяющим раскладку файла.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.tickets.enums import (
    AccessLevel,
    TicketChannel,
    TicketPriority,
    TicketStatus,
    TicketTeam,
    TicketType,
)

# tests/unit/tickets/test_enums.py -> parents[3] == backend, parents[4] == repo root
OPENAPI_PATH = (
    Path(__file__).resolve().parents[4] / "docs" / "handoff" / "01_postanovka" / "04_openapi.yaml"
)


def _schema_enum_values(name: str) -> set[str]:
    """Извлечь множество значений `enum:` у top-level схемы `name`.

    Блок схемы — строки с отступом > 4 пробелов (или пустые) после строки
    `    <name>:`; заканчивается на следующей 4-пробельной схеме.
    """
    lines = OPENAPI_PATH.read_text(encoding="utf-8").splitlines()
    values: list[str] = []
    in_block = False
    in_enum = False
    for line in lines:
        if line == f"    {name}:":
            in_block = True
            continue
        if not in_block:
            continue
        # Конец блока схемы — следующая схема на 4-пробельном отступе.
        if re.match(r"^ {4}[A-Za-z]", line):
            break
        stripped = line.strip()
        if stripped == "enum:":
            in_enum = True
            continue
        if in_enum:
            if stripped.startswith("- "):
                values.append(stripped[2:].strip())
            elif stripped:  # любая другая ключевая строка завершает enum-список
                in_enum = False
    return set(values)


@pytest.mark.parametrize(
    ("enum_cls", "schema_name"),
    [
        (TicketStatus, "TicketStatus"),
        (TicketPriority, "TicketPriority"),
        (TicketType, "TicketType"),
        (TicketChannel, "TicketChannel"),
        (TicketTeam, "TicketTeam"),
    ],
)
def test_enum_matches_openapi_contract(
    enum_cls: type[TicketStatus]
    | type[TicketPriority]
    | type[TicketType]
    | type[TicketChannel]
    | type[TicketTeam],
    schema_name: str,
) -> None:
    """Множество значений Python-энума == множеству значений в контракте."""
    contract = _schema_enum_values(schema_name)
    assert contract, f"не удалось извлечь enum {schema_name} из контракта"
    assert {member.value for member in enum_cls} == contract


def test_parser_finds_known_values() -> None:
    """Самопроверка парсера: TicketType из контракта содержит claims-типы."""
    values = _schema_enum_values("TicketType")
    assert {"COMPENSATION", "GUARANTEE", "INSURANCE", "ACCEPTANCE_ACT"} <= values
    assert len(values) == 16


def test_access_level_values() -> None:
    """`access_level` объявлен inline в схеме Ticket (ADR-0003) — сверяем явно."""
    assert {member.value for member in AccessLevel} == {
        "PUBLIC",
        "LOGGED",
        "AGENT",
        "STAFF",
        "LEGAL",
        "HR_RESTRICTED",
    }


def test_enum_members_are_str() -> None:
    """`(str, Enum)` — член равен своей строке и является str (прямая сериализация)."""
    assert isinstance(TicketStatus.NEW, str)
    # Член — это его строка (str-mixin). Типизируем как str, чтобы assert был
    # сравнением str==str (mypy strict: иначе comparison-overlap на Literal-членах).
    status: str = TicketStatus.NEW
    priority: str = TicketPriority.LOW
    team: str = TicketTeam.SUPPORT
    assert status == "NEW"
    assert priority == "low"
    assert team == "support"
