"""Unit-тесты чистых селекторов стратегий назначения (#109) — без БД.

Покрывают: least_load (минимум + тай-брейк по operator_id, в т.ч. при равном НУЛЕ);
round_robin (детерминизм, цикл, независимость от порядка входа, пул из одного).
Live-query (`resolve_assignee` / `_count_*`) — в integration-тестах (нужен Postgres).
"""

from __future__ import annotations

import uuid

from api.automation.assignment import _select_least_loaded, _select_round_robin

# Фиксированные UUID с заведомо известным порядком сортировки (по первому байту).
OP1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
OP2 = uuid.UUID("00000000-0000-4000-8000-000000000002")
OP3 = uuid.UUID("00000000-0000-4000-8000-000000000003")
_SORTED = [OP1, OP2, OP3]


def test_least_loaded_picks_minimum() -> None:
    counts = {OP1: 5, OP2: 1, OP3: 3}
    assert _select_least_loaded(_SORTED, counts) == OP2


def test_least_loaded_zero_load_candidate_included() -> None:
    # OP3 нет в counts (нет активных заявок) → трактуется как 0 и выбирается.
    counts = {OP1: 2, OP2: 1}
    assert _select_least_loaded(_SORTED, counts) == OP3


def test_least_loaded_tiebreak_by_operator_id() -> None:
    # Равная НЕнулевая загрузка → минимальный operator_id.
    counts = {OP1: 2, OP2: 2, OP3: 2}
    assert _select_least_loaded(_SORTED, counts) == OP1


def test_least_loaded_tiebreak_at_equal_zero() -> None:
    # Реальный старт: у всех 0 активных → детерминированно минимальный operator_id.
    assert _select_least_loaded(_SORTED, {}) == OP1


def test_least_loaded_single_pool() -> None:
    assert _select_least_loaded([OP2], {}) == OP2


def test_round_robin_cycles_deterministically() -> None:
    # Позиция = rotation_count mod len(pool); монотонный счётчик → ровный цикл.
    assert _select_round_robin(_SORTED, 0) == OP1
    assert _select_round_robin(_SORTED, 1) == OP2
    assert _select_round_robin(_SORTED, 2) == OP3
    assert _select_round_robin(_SORTED, 3) == OP1  # цикл замкнулся


def test_round_robin_is_pure() -> None:
    # Один и тот же вход → один и тот же выход (чистота).
    assert _select_round_robin(_SORTED, 7) == _select_round_robin(_SORTED, 7)


def test_round_robin_independent_of_input_order() -> None:
    # Резолвер сортирует пул; селектор на отсортированном даёт результат, не зависящий
    # от исходного порядка тех же элементов.
    shuffled = sorted([OP3, OP1, OP2])
    assert _select_round_robin(shuffled, 4) == _select_round_robin(_SORTED, 4)


def test_round_robin_single_pool() -> None:
    # Граница `% 1 == 0` — единственный оператор при любом счётчике.
    assert _select_round_robin([OP2], 0) == OP2
    assert _select_round_robin([OP2], 99) == OP2
