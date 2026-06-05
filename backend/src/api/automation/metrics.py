"""Prometheus-метрики движка автоматизации (E5-4 #106; ADR-0008 Реш.4).

Неймспейс `automation_*` (эталон — `tickets/sla_metrics.py`). Регистрируются в
дефолтном реестре prometheus_client → попадают в существующий `/metrics`. Лейблы
низкой кардинальности, без ПДн (`ticket_id` НЕ используется; `rule_id` — bounded
admin-набор правил, кардинальность приемлема).

`automation_rule_failed_total` — сбой исполнения действия правила (best-effort
изоляция, ADR-0008 Реш.4: «no silent caps» — сбой ВИДЕН на дашборде, не молчит).
`automation_action_deferred_total` — действие не применилось из-за нереализованной
возможности (напр. assign round_robin/least_load БЕЗ пула операторов — пул из platform
до #77) — наблюдаемый недо-резолв, не сбой.

Запись идёт ВНУТРИ транзакции (как `sla_metrics`): откат БД метрику не отменит —
допустимый компромисс (исполнение #107 — best-effort, откат маловероятен).
"""

from __future__ import annotations

from prometheus_client import Counter

AUTOMATION_RULE_FAILED = Counter(
    "automation_rule_failed_total",
    "Сбои исполнения действий правил автоматизации (best-effort, ADR-0008 Реш.4).",
    ["rule_id", "action", "trigger"],
)

AUTOMATION_ACTION_DEFERRED = Counter(
    "automation_action_deferred_total",
    "Действия, не применённые из-за нереализованной возможности (assign-стратегия без пула, #77).",
    ["action", "reason"],
)


def record_rule_failure(*, rule_id: str, action: str, trigger: str) -> None:
    """Инкремент счётчика сбоя действия правила (rule_id/action/trigger — без ПДн)."""
    AUTOMATION_RULE_FAILED.labels(rule_id=rule_id, action=action, trigger=trigger).inc()


def record_action_deferred(*, action: str, reason: str) -> None:
    """Инкремент счётчика отложенного действия (наблюдаемый недо-резолв, не сбой)."""
    AUTOMATION_ACTION_DEFERRED.labels(action=action, reason=reason).inc()
