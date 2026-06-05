"""time_based-воркер автоматизации (E5, #110): Dramatiq-actor периодического прогона.

Config-gated (ADR-0008 Реш.6): без `sla_worker_broker_url` (единый broker сервиса) actor
инертен (StubBroker). Источник истины — БД (NFR-3.2): скан по временным условиям правил.
Боевой путь — после ops (broker/worker, #79).
"""
