"""Доменный DTO клиента страховщика (E10-10 PR-B #200).

Наша модель, независимая от провизорной формы (ADR-0014:67/0017). Только id — ПДн наружу
не передаём (ФЗ-152). `insurance_event_id` может быть None (провизорно — страховщик присвоит).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class InsurerEvent:
    """Событие INSURANCE-заявки для передачи страховщику (ADR-0014:67)."""

    ticket_id: uuid.UUID
    insurance_event_id: uuid.UUID | None
