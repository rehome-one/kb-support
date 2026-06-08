"""Аналитика службы поддержки (E8, эпик #21).

Ядро агрегации сводных метрик (E8-1, #165): период (`period`), DTO агрегатов
(`dto`), SQL-агрегаты по своей БД (`repository`), сборка + cache-aside (`service`).

Архитектурная константа (ADR-0011 Решение 2, NFR-4.4): аналитика считается ТОЛЬКО
по своей БД kb-support, без внешнего warehouse. Эндпоинт `GET /support/stats`,
RBAC `staff_supervisor`, типизация контракта и kb-search containment-seam — в #166.
"""
