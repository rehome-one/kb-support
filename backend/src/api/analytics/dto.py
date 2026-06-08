"""DTO сводных метрик аналитики (E8-1, #165) — чистые frozen-dataclass.

Зеркалят секции схемы `SupportStats` (`docs/openapi.yaml`): tickets / sla /
performance / quality / ai_chat. Типизированный pydantic-ответ контракта строит
роутер #166 — здесь только внутренние данные ядра.

**Инвариант нулевого знаменателя (ADR-0011 Решение 4):** поля `*_pct` / `avg_*` при
нулевом знаменателе = `None` (не `0`, не `NaN`); счётчики (`*_count` / `breaches` /
`total` / ...) = `0`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from api.analytics.period import StatsPeriod


@dataclass(frozen=True)
class TicketCounts:
    """Объёмы заявок за период.

    `total`/`resolved`/`closed`/`by_type`/`by_channel` — КОГОРТНЫЕ (заявки, созданные
    в периоде, ADR-0011 Решение 4). `open` — **СНАПШОТ** (решение Архитектора
    2026-06-08, FR-7.1): сколько заявок открыто СЕЙЧАС (status ∉ терминальных, без
    верхней границы периода). Поэтому **`open + resolved + closed` НЕ обязано равняться
    `total`** — это разные оси (снапшот vs когорта); равенством не пользоваться.
    """

    total: int
    open: int
    resolved: int
    closed: int
    by_type: dict[str, int]
    by_channel: dict[str, int]


@dataclass(frozen=True)
class SlaStats:
    """Соблюдение SLA за период.

    `*_compliance_pct` — по когорте «завершившихся в периоде» (first_responded_at /
    resolved_at ∈ period). `breaches` — по когорте created-в-периоде на момент `now`
    (оценка через единый breach-предикат `tickets/sla_query`). **`breaches` НЕ обязан
    совпадать с `(1 − compliance)·N`** — у них разные якоря периода (условие 1 ревью
    #165): просроченная, но ещё не завершённая заявка входит в `breaches`, но не в
    знаменатель compliance.
    """

    first_response_compliance_pct: float | None
    resolution_compliance_pct: float | None
    breaches: int


@dataclass(frozen=True)
class PerformanceStats:
    """Производительность за период.

    `avg_first_response_minutes` — wall-clock `first_responded_at − created_at` по
    заявкам с first_responded_at ∈ period (он же «время в очереди» FR-7.3).
    `avg_resolution_minutes` — wall-clock `resolved_at − created_at` по resolved ∈
    period. **Намеренно wall-clock, НЕ pause-adjusted** (условие 2 ревью #165):
    pause-adjusted TTR экспортирует `tickets/sla_metrics` #91 в Grafana — это другая
    метрика («рабочее время без пауз»), здесь — «время решения» буквально.
    `reopened_rate_pct` — доля заявок с `reopened_count > 0` среди созданных в периоде.
    """

    avg_first_response_minutes: float | None
    avg_resolution_minutes: float | None
    reopened_rate_pct: float | None


@dataclass(frozen=True)
class QualityStats:
    """Удовлетворённость за период: средняя оценка и число оценок.

    По заявкам, созданным в периоде, с `rating IS NOT NULL`. **ФЗ-152:** читается
    только числовой `rating`, НЕ `rating_comment`.
    """

    avg_rating: float | None
    ratings_count: int


@dataclass(frozen=True)
class AiChatStats:
    """Метрики первой линии (kb-search) за период.

    `escalated_count` — заявки `channel=AI_CHAT`, созданные в периоде (считаем сами).
    `containment_rate_pct` — доля диалогов без эскалации; истинный знаменатель живёт
    в kb-search → **config-gated seam в #166** (ADR-0011 Решение 3). В ядре #165 всегда
    `None` (граница-заглушка до #166).
    """

    containment_rate_pct: float | None
    escalated_count: int


@dataclass(frozen=True)
class OperatorStat:
    """Эффективность оператора за период (E8-3, #167; отчёт operators).

    **resolved-anchor (решение Архитектора)**: считается по заявкам, РЕШЁННЫМ в периоде
    (`resolved_at ∈ period`), GROUP BY `assignee_id`. `avg_resolution_minutes` — по тому же
    набору (`resolved_at − created_at`, нулевой знаменатель → None). ФЗ-152: только uuid
    оператора + счётчики, без имён/ПДн.
    """

    operator_id: uuid.UUID
    resolved_count: int
    avg_resolution_minutes: float | None


@dataclass(frozen=True)
class SupportStatsData:
    """Сводные метрики поддержки за период (внутренний результат ядра аналитики)."""

    period: StatsPeriod
    tickets: TicketCounts
    sla: SlaStats
    performance: PerformanceStats
    quality: QualityStats
    ai_chat: AiChatStats
