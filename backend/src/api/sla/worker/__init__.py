"""SLA-воркер (E4-6, #90): Dramatiq-actor проактивной проверки дедлайнов.

Config-gated (ADR-0007 Решение 1): без `sla_worker_broker_url` actor инертен
(StubBroker). Источник истины — БД (NFR-3.2). Действия эскалации (FR-4.4) — E5/#18,
здесь только breach-хук-seam. Боевой путь — после ops (broker/worker, #79).
"""
