"""Календарные/рабочие сроки претензий по Договору (E10-6 #196, §3.8, FR-9).

Сроки Договора — юридические константы, НЕ admin-настройка (решение Архитектора Q1,
Вариант B): задаются здесь, а не через `SLAPolicy` (та — минуты/бизнес-часы общего
саппорта, E4). Чистые функции (без I/O), `anchor` инъектируется.

- рассмотрение: 30 КАЛЕНДАРНЫХ дней (Договор 5.8.7) → `compute_review_due_at`;
  кладётся в `Ticket.resolution_due_at` (решение Архитектора Q3) — так дедлайн
  подключается к существующей breach-машине E4 (read-side #89 + worker #90) без
  нового кода.
- выплата: 10 РАБОЧИХ дней (Договор 5.8.8) → `compute_payout_due_at`; якорь —
  вход в PAYOUT_PENDING (решение Архитектора Q2).
- регресс GUARANTEE: 14 КАЛЕНДАРНЫХ дней (Договор 5.8.8) → `compute_regress_due_at`
  (фиксация-seam, боевой путь — платёжный контур, D2/upstream).

Праздники РФ в расчёте рабочих дней пока НЕ учитываются (только выходные Сб/Вс) —
follow-up, тот же прецедент, что business hours в ADR-0007 Реш.3.
"""

from __future__ import annotations

import datetime

# Сроки Договора (§3.8 / 5.8) — юридические константы (решение Архитектора Q1).
REVIEW_CALENDAR_DAYS = 30  # 5.8.7 рассмотрение претензии
PAYOUT_BUSINESS_DAYS = 10  # 5.8.8 выплата после решения
REGRESS_CALENDAR_DAYS = 14  # 5.8.8 регрессное обязательство (GUARANTEE)

_SATURDAY = 5  # weekday(): Пн=0 … Пт=4, Сб=5, Вс=6 → рабочий день < 5


def compute_review_due_at(anchor: datetime.datetime) -> datetime.datetime:
    """Дедлайн рассмотрения = anchor + 30 КАЛЕНДАРНЫХ дней (Договор 5.8.7)."""
    return anchor + datetime.timedelta(days=REVIEW_CALENDAR_DAYS)


def compute_regress_due_at(anchor: datetime.datetime) -> datetime.datetime:
    """Дедлайн регресса = anchor + 14 КАЛЕНДАРНЫХ дней (Договор 5.8.8, GUARANTEE)."""
    return anchor + datetime.timedelta(days=REGRESS_CALENDAR_DAYS)


def compute_payout_due_at(anchor: datetime.datetime) -> datetime.datetime:
    """Дедлайн выплаты = anchor + 10 РАБОЧИХ дней (Договор 5.8.8).

    Рабочий день — Пн–Пт; Сб/Вс пропускаются. Время суток якоря сохраняется.
    Праздники РФ не учитываются (follow-up, как business hours ADR-0007 Реш.3).
    """
    result = anchor
    remaining = PAYOUT_BUSINESS_DAYS
    while remaining > 0:
        result += datetime.timedelta(days=1)
        if result.weekday() < _SATURDAY:  # Пн–Пт
            remaining -= 1
    return result
