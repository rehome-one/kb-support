"""Доменные перечисления Ticket — ТЗ v2.2 §3.2 (статусы), §3.3+3.3a (типы),
§3.4 (каналы), ADR-0003 (контуры доступа `access_level`).

Значения строк — **дословно** из контракта
`docs/handoff/01_postanovka/04_openapi.yaml` (схемы TicketStatus / TicketPriority
/ TicketType / TicketChannel / TicketTeam и inline `access_level` в Ticket).
Контракт immutable — он источник правды домена (решение Архитектора 2026-05-30,
Issue #5).

Перечисления хранятся в БД как `String`, а не нативный PG ENUM: справочники
статусов/типов/каналов настраиваемы администратором (§3.2/§3.3), поэтому домен
валидируется на уровне приложения, без `ALTER TYPE`. Сами Enum-классы здесь —
seed-набор по умолчанию и валидатор на границе API.

Базовые значения покрывают весь домен контракта, включая претензионные типы
(COMPENSATION/GUARANTEE/INSURANCE/ACCEPTANCE_ACT) и их каналы
(LK_CLAIM/INSURER_WEBHOOK/SYSTEM). **Поведение** претензионных типов (поля
§3.1.1, case_state) — это E10 (#23); на E1 присутствует только значение домена.
"""

from __future__ import annotations

import enum


class TicketStatus(str, enum.Enum):
    """Базовый жизненный цикл заявки (ТЗ §3.2). Настраивается администратором."""

    NEW = "NEW"
    OPEN = "OPEN"
    PENDING = "PENDING"
    WAITING = "WAITING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class TicketPriority(str, enum.Enum):
    """Приоритет заявки (ТЗ §3.1)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TicketType(str, enum.Enum):
    """Тип обращения (ТЗ §3.3 + 3.3a). Настраиваемый справочник.

    Последние четыре значения — претензионные типы (flow v3). На E1 — только
    значение домена; их поведение (поля §3.1.1, case_state) реализуется в E10.
    """

    PAYMENT = "PAYMENT"
    CONTRACT = "CONTRACT"
    MOVE_IN = "MOVE_IN"
    MOVE_OUT = "MOVE_OUT"
    MAINTENANCE = "MAINTENANCE"
    UTILITIES = "UTILITIES"
    ACCOUNT = "ACCOUNT"
    LISTING = "LISTING"
    COLLABORATOR = "COLLABORATOR"
    COMPLAINT = "COMPLAINT"
    FRAUD = "FRAUD"
    COMPENSATION = "COMPENSATION"
    GUARANTEE = "GUARANTEE"
    INSURANCE = "INSURANCE"
    ACCEPTANCE_ACT = "ACCEPTANCE_ACT"
    OTHER = "OTHER"


class TicketChannel(str, enum.Enum):
    """Канал поступления (ТЗ §3.4). AI_CHAT — главный (эскалация из kb-search).

    LK_CLAIM/INSURER_WEBHOOK/SYSTEM — каналы претензионных типов (v1.1).
    """

    AI_CHAT = "AI_CHAT"
    EMAIL = "EMAIL"
    WEB_FORM = "WEB_FORM"
    PHONE = "PHONE"
    INTERNAL = "INTERNAL"
    LK_CLAIM = "LK_CLAIM"
    INSURER_WEBHOOK = "INSURER_WEBHOOK"
    SYSTEM = "SYSTEM"


class TicketTeam(str, enum.Enum):
    """Команда обработки (ТЗ §3.1). Специализация claims — через scope/тег,
    без отдельного значения enum (§3.3a, §8.1)."""

    SUPPORT = "support"
    LEGAL = "legal"
    FINANCE = "finance"


class AuthorType(str, enum.Enum):
    """Тип автора сообщения (ТЗ §3.5). Выводится из принципала, не из payload."""

    REQUESTER = "requester"
    OPERATOR = "operator"
    SYSTEM = "system"
    AI = "ai"


class AccessLevel(str, enum.Enum):
    """Контур доступа (ADR-0003). PUBLIC/LOGGED/AGENT — публичный контур;
    STAFF/LEGAL/HR_RESTRICTED — внутренний. Не смешивать (CLAUDE.md §«двухконтурность»)."""

    PUBLIC = "PUBLIC"
    LOGGED = "LOGGED"
    AGENT = "AGENT"
    STAFF = "STAFF"
    LEGAL = "LEGAL"
    HR_RESTRICTED = "HR_RESTRICTED"


# --- Претензионные типы (E10, §3.2.1/3.3/3.11, ADR-0013). Домены — из immutable-контракта
# (docs/openapi.yaml). String-хранение + валидация Python-энумом (без native PG ENUM, §3.2/3.3).


class CaseType(str, enum.Enum):
    """Тип претензионного обращения (§3.11, TicketCaseDetails.case_type)."""

    COMPENSATION = "COMPENSATION"
    GUARANTEE = "GUARANTEE"
    INSURANCE = "INSURANCE"
    ACCEPTANCE_ACT = "ACCEPTANCE_ACT"


class TicketCaseState(str, enum.Enum):
    """Состояние разбирательства (§3.2.1). Ведётся параллельно базовому status.

    ТЗ задаёт линейную цепочку; детальная таблица переходов — `case_state_machine` (E10-2,
    ADR-0013 D5). Терминалы: PAID, REJECTED."""

    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    DOCS_PENDING = "DOCS_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    INSPECTION = "INSPECTION"
    DECISION_MADE = "DECISION_MADE"
    PAYOUT_PENDING = "PAYOUT_PENDING"
    PAID = "PAID"
    REJECTED = "REJECTED"


class TicketDecision(str, enum.Enum):
    """Решение по претензии (Договор 5.8.8). reason обязателен при PARTIAL/REJECTED (E10-3)."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class InsurerDecision(str, enum.Enum):
    """Вердикт страховщика по INSURANCE-заявке (provisional contract, ADR-0017 D2).

    Решение по выплате — за страховщиком (FR-9.6, §3.3.3); kb-support лишь ФИКСИРУЕТ его и
    системно двигает case_state по машине E10-2: APPROVED → DECISION_MADE, REJECTED → REJECTED.
    Это НЕ наш внутренний вердикт (`TicketDecision`/`decide()`) — `ticket.decision` не трогаем.
    Точные значения upstream-контракта страховщика не зафиксированы — провизорный минимум
    (без PARTIAL: деньги/суммы не считаем, FR-9.8); расширение — follow-up при боевом контракте."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ActKind(str, enum.Enum):
    """Тип акта приёма-передачи (§3.3.4). MOVE_OUT+ущерб → каскад COMPENSATION (D9, E10-9)."""

    MOVE_IN = "MOVE_IN"
    MOVE_OUT = "MOVE_OUT"


class SigningStatus(str, enum.Enum):
    """Статус двустороннего SMS-OTP подписания акта (§3.3.4)."""

    ONE_SIGNED = "one_signed"
    BOTH_SIGNED = "both_signed"
    DISPUTED = "disputed"
