#!/usr/bin/env python3
"""Сгенерировать production `docs/openapi.yaml` из immutable handoff (#11).

Handoff `docs/handoff/01_postanovka/04_openapi.yaml` (ТЗ Приложение A) — immutable,
содержит legacy OpenAPI 3.0 `nullable: true`, что недопустимо в 3.1 (redocly struct
rule → errors). Этот генератор нормализует его в 3.1:

    type: <T>            type: [<T>, "null"]
    nullable: true   →   (nullable удалён)

Поверхность контракта (пути/схемы/коды) НЕ меняется — только нормализация nullable.

Запуск (нужен PyYAML из dev-окружения):
    backend/.venv/bin/python scripts/generate_production_openapi.py

Требует pyyaml. OUTPUT коммитится в репозиторий; в рантайме сервиса генератор не нужен.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
HANDOFF = ROOT / "docs" / "handoff" / "01_postanovka" / "04_openapi.yaml"
OUTPUT = ROOT / "docs" / "openapi.yaml"

HEADER = (
    "# GENERATED — не редактировать вручную.\n"
    "# Источник: docs/handoff/01_postanovka/04_openapi.yaml (immutable handoff, ТЗ Приложение A).\n"
    "# Генератор: scripts/generate_production_openapi.py — нормализация OpenAPI 3.1:\n"
    '#   legacy `nullable: true` → `type: [<type>, "null"]`. Поверхность контракта не меняется.\n'
    "# Регенерация: backend/.venv/bin/python scripts/generate_production_openapi.py\n"
)


def normalize(node: Any) -> None:
    """Рекурсивно заменить `nullable: true` на 3.1 `type: [<type>, "null"]` (in place)."""
    if isinstance(node, dict):
        if node.get("nullable") is True:
            node.pop("nullable")
            current = node.get("type")
            if isinstance(current, str):
                node["type"] = [current, "null"]
        for value in node.values():
            normalize(value)
    elif isinstance(node, list):
        for item in node:
            normalize(item)


def main() -> None:
    spec = yaml.safe_load(HANDOFF.read_text(encoding="utf-8"))
    normalize(spec)
    body = yaml.safe_dump(
        spec,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    OUTPUT.write_text(HEADER + body, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
