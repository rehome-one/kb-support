"""Стратегии автоназначения для action=assign (E5 #109; ADR-0008 Решение 5).

Резолвит исполнителя по стратегии:
- **least_load** — оператор с наименьшим числом АКТИВНЫХ (не-терминальных) заявок в
  целевой команде через live-query (без stateful-таблицы счётчиков). Тай-брейк при
  равной загрузке — детерминированный по `operator_id` (asc). Осознанно НЕ атомарен
  под гонкой (ADR-0008 Реш.5) — для автоназначения допустимо.
- **round_robin** — детерминированный, НЕ-stateful обход пула по `operator_id`.
  Базис ротации (решение Архитектора, Вариант A) — КУМУЛЯТИВНЫЙ счётчик заявок
  команды, назначенных операторам пула, по ВСЕМ статусам (монотонный → ровная
  ротация). Известное ограничение: при переназначениях/смене состава пула счётчик
  может сместиться — это НЕ stateful-fair ротация с историческим курсором (тот
  отвергнут ADR-0008 Реш.5: лишнее состояние и гонки).

Терминальность берётся из ЕДИНОГО источника `state_machine.TERMINAL_STATUSES`
(ADR-0008 Реш.5: без хардкода списка). Источник пула операторов — seam #77
(`params.pool`; реальный platform-источник ролей включится позже без правки стратегий).

Текущая заявка ИСКЛЮЧАЕТСЯ из live-query (`id != current`): на on_create она уже
во flush'нута (статус NEW, не-терминальный) и иначе исказила бы счётчики (off-by-one),
а поведение должно быть независимо от момента flush.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.automation.enums import AssignStrategy
from api.tickets.enums import TicketTeam
from api.tickets.models import Ticket
from api.tickets.state_machine import TERMINAL_STATUSES

# Строковая проекция канона для live-query (Ticket.status — String(32), не enum).
_TERMINAL_VALUES = [status.value for status in TERMINAL_STATUSES]


def _select_least_loaded(pool_sorted: list[uuid.UUID], counts: dict[uuid.UUID, int]) -> uuid.UUID:
    """Минимально загруженный из пула; тай-брейк детерминированный по operator_id (asc).

    `counts` — активная загрузка по operator_id; отсутствующий кандидат = 0.
    `pool_sorted` непуст (гарантирует вызывающий)."""
    return min(pool_sorted, key=lambda operator_id: (counts.get(operator_id, 0), operator_id))


def _select_round_robin(pool_sorted: list[uuid.UUID], rotation_count: int) -> uuid.UUID:
    """Детерминированный обход пула: позиция = rotation_count mod размер пула.

    Чистая функция от (отсортированный пул, счётчик): один и тот же вход → один и тот
    же оператор; порядок исходного пула не влияет (сортировка — на стороне резолвера).
    `pool_sorted` непуст."""
    return pool_sorted[rotation_count % len(pool_sorted)]


async def _count_active_by_assignee(
    session: AsyncSession,
    team: TicketTeam,
    pool_sorted: list[uuid.UUID],
    current_ticket_id: uuid.UUID,
) -> dict[uuid.UUID, int]:
    """Число активных (не-терминальных) заявок в команде по каждому оператору пула."""
    stmt = (
        select(Ticket.assignee_id, func.count())
        .where(
            Ticket.team == team.value,
            Ticket.assignee_id.in_(pool_sorted),
            Ticket.status.notin_(_TERMINAL_VALUES),
            Ticket.id != current_ticket_id,
        )
        .group_by(Ticket.assignee_id)
    )
    rows = await session.execute(stmt)
    return {assignee_id: count for assignee_id, count in rows if assignee_id is not None}


async def _count_assigned_total(
    session: AsyncSession,
    team: TicketTeam,
    pool_sorted: list[uuid.UUID],
    current_ticket_id: uuid.UUID,
) -> int:
    """Кумулятивный счётчик round-robin: заявки команды на операторов пула, ВСЕ статусы."""
    stmt = select(func.count()).where(
        Ticket.team == team.value,
        Ticket.assignee_id.in_(pool_sorted),
        Ticket.id != current_ticket_id,
    )
    return (await session.execute(stmt)).scalar_one()


async def resolve_assignee(
    session: AsyncSession,
    *,
    strategy: AssignStrategy,
    team: TicketTeam | None,
    pool: list[uuid.UUID] | None,
    current_ticket_id: uuid.UUID,
) -> uuid.UUID | None:
    """Выбрать оператора по стратегии. `None` — пул/команда не заданы (недо-резолв, seam #77).

    `team` для стратегий гарантирован валидатором `AssignParams`; `None` тут — защитно.
    TODO(#77): валидация принадлежности пула команде/существования оператора — после
    platform-источника ролей. До него «фантомный» operator_id из пула least_load выберет
    в первую очередь (его активная загрузка = 0) — known-limitation, видимое, не молчит.
    """
    if not pool or team is None:
        return None
    pool_sorted = sorted(pool)
    if strategy is AssignStrategy.LEAST_LOAD:
        counts = await _count_active_by_assignee(session, team, pool_sorted, current_ticket_id)
        return _select_least_loaded(pool_sorted, counts)
    if strategy is AssignStrategy.ROUND_ROBIN:
        rotation_count = await _count_assigned_total(session, team, pool_sorted, current_ticket_id)
        return _select_round_robin(pool_sorted, rotation_count)
    return None  # DIRECT сюда не приходит (обрабатывается в _exec_assign)
