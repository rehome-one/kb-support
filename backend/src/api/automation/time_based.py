"""Скан time_based-правил автоматизации (E5, #110; FR-3.1, NFR-3.2, ADR-0008 Реш.6/7).

Периодический actor (`api.automation.worker`) запускает `scan_time_based`: для каждого
активного time_based-правила выбирает заявки, удовлетворяющие временному условию правила
(`inactive_minutes` / `unanswered_minutes`), и применяет действия правила (#106/#107).

**Источник истины — БД** (NFR-3.2): расписание не в памяти, скан по `updated_at`/
`created_at`/`first_responded_at` → переживает перезапуск.

**Временной предикат** имеет два согласованных представления — SQL-клаузу
(`time_predicate_clause`, выборка) и чистое зеркало (`time_predicate_satisfied`,
unit-тест) — на одном наборе (паттерн #89 `sla_query`↔`sla_state`). Граница `<=` (как
SLA breach). UTC-арифметика интервалов (`updated_at`/`created_at` хранятся в UTC) — без
business-hours-сложности.

**Статич. измерения** (type/priority/channel/statuses/keywords) — чистый матчер #105:
SQL пре-фильтрует по времени + статусам (эффективность), матчер досматривает остальное.
Терминальные статусы (`state_machine.TERMINAL_STATUSES`) исключены всегда; `statuses`
далее сужает (терминальный `statuses` на time_based → пустое пересечение, правило молчит).

**Дедуп через `updated_at`** (решение Архитектора, без колонки): мутирующее действие
(set_status / set_priority / add_tag-с-изменением / escalate / assign) делает flush →
строка UPDATE → `updated_at` бьётся (TimestampMixin `onupdate`) → часы неактивности
сбрасываются → правило не переприменяется на той же заявке.
**KNOWN-LIMITATION:** действия-no-op (идемпотентный `add_tag` без изменений — ранний
return в `actions.py`; отклонённый `transition` — откат savepoint) НЕ меняют `updated_at`
→ правило переприменяется каждый проход. Наследует ограничение `notify`-seam и
breach-эскалаций (#120); инертно до ops-воркера (#79).
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping

from sqlalchemy import ColumnElement, Select, and_, false, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.automation.engine import run_actions
from api.automation.enums import AutomationTrigger
from api.automation.matcher import conditions_match
from api.automation.repository import AutomationRuleRepository
from api.observability.logging import get_logger
from api.tickets.models import Ticket
from api.tickets.state_machine import TERMINAL_STATUSES

_logger = get_logger("automation.time_based")

# Проекция терминальных статусов в строковые значения для SQL `.notin_()`
# (state_machine.py предписывает не подставлять frozenset enum'ов в notin_).
_TERMINAL_VALUES = [status.value for status in TERMINAL_STATUSES]


def _as_positive_int(value: object) -> int | None:
    """Положительный int из сырого JSONB (bool — НЕ int здесь; защита от мусора)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 1:
        return value
    return None


def time_predicate_clause(
    conditions: Mapping[str, object], now: datetime.datetime
) -> ColumnElement[bool]:
    """SQL-предикат временного условия (конъюнкция заданных порогов).

    `inactive_minutes` → `updated_at <= now - N мин`; `unanswered_minutes` →
    `first_responded_at IS NULL AND created_at <= now - N мин`. Без временных полей →
    `false()` (правило не матчит ничего — защитный дефолт; схема требует ≥1 поля)."""
    clauses: list[ColumnElement[bool]] = []
    inactive = _as_positive_int(conditions.get("inactive_minutes"))
    if inactive is not None:
        clauses.append(Ticket.updated_at <= now - datetime.timedelta(minutes=inactive))
    unanswered = _as_positive_int(conditions.get("unanswered_minutes"))
    if unanswered is not None:
        clauses.append(
            and_(
                Ticket.first_responded_at.is_(None),
                Ticket.created_at <= now - datetime.timedelta(minutes=unanswered),
            )
        )
    if not clauses:
        return false()
    return and_(*clauses)


def time_predicate_satisfied(
    ticket: Ticket, conditions: Mapping[str, object], now: datetime.datetime
) -> bool:
    """Чистое зеркало `time_predicate_clause` (unit-тест; единый источник правды #89)."""
    inactive = _as_positive_int(conditions.get("inactive_minutes"))
    unanswered = _as_positive_int(conditions.get("unanswered_minutes"))
    if inactive is None and unanswered is None:
        return False
    if inactive is not None and ticket.updated_at > now - datetime.timedelta(minutes=inactive):
        return False
    if unanswered is not None:
        if ticket.first_responded_at is not None:
            return False
        if ticket.created_at > now - datetime.timedelta(minutes=unanswered):
            return False
    return True


def select_candidates(
    conditions: Mapping[str, object], now: datetime.datetime, *, batch_limit: int
) -> Select[tuple[Ticket]]:
    """Заявки-кандидаты правила: непросроченный временной предикат + статусы + non-terminal.

    Детерминированный порядок (`updated_at asc, id asc`) — иначе при насыщении
    `batch_limit` одни и те же заявки систематически вытеснялись бы за лимит."""
    stmt = select(Ticket).where(
        Ticket.status.notin_(_TERMINAL_VALUES),
        time_predicate_clause(conditions, now),
    )
    statuses = conditions.get("statuses")
    if isinstance(statuses, list) and statuses:
        stmt = stmt.where(Ticket.status.in_([s for s in statuses if isinstance(s, str)]))
    return stmt.order_by(Ticket.updated_at.asc(), Ticket.id.asc()).limit(batch_limit)


async def scan_time_based(
    session: AsyncSession, *, now: datetime.datetime, batch_limit: int
) -> int:
    """Прогнать все активные time_based-правила по подходящим заявкам. Возвращает число
    срабатываний (rule×ticket). Best-effort: сбой одного правила не валит проход."""
    rules = await AutomationRuleRepository(session).list_active(AutomationTrigger.TIME_BASED.value)
    fired = 0
    for rule in rules:
        try:
            result = await session.execute(
                select_candidates(rule.conditions, now, batch_limit=batch_limit)
            )
            rows = list(result.scalars().all())
            if len(rows) == batch_limit:
                # No silent caps: проход насыщён, остаток отложен до следующего скана.
                _logger.warning(
                    "time_based_scan batch saturated rule_id=%s limit=%s — остаток отложен",
                    rule.id,
                    batch_limit,
                )
            for ticket in rows:
                # Досмотр статич. измерений матчером #105 (time-поля он не оценивает).
                ticket_text = f"{ticket.subject}\n{ticket.description}"
                if not conditions_match(
                    rule.conditions,
                    ticket_type=ticket.type,
                    ticket_priority=ticket.priority,
                    ticket_channel=ticket.channel,
                    ticket_status=ticket.status,
                    ticket_text=ticket_text,
                ):
                    continue
                await run_actions(
                    session,
                    ticket,
                    rule.actions,
                    rule_id=rule.id,
                    trigger=AutomationTrigger.TIME_BASED.value,
                )
                fired += 1
        except Exception:
            # Сбой правила (выборка/матчинг) изолирован — проход не валится (Реш.4); ПДн нет.
            _logger.error("time_based_rule_failed rule_id=%s", rule.id, exc_info=True)
            continue
    return fired
