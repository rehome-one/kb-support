"""Prometheus-метрики приёма входящего email (E7-4, #146).

Неймспейс `email_*` — приём писем из IMAP-ящика поддержки. Регистрируются в
дефолтном реестре prometheus_client → попадают в существующий `/metrics`.
Лейблы низкой кардинальности, БЕЗ ПДн (никаких адресов/тем/тел — только исходы).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# Геометрический ряд байтов (1КБ…10МБ) — распределение размеров принятых вложений.
_ATTACHMENT_SIZE_BUCKETS = (1024, 8192, 65536, 262144, 1048576, 5242880, 10485760)

EMAIL_FETCHED = Counter(
    "email_fetched_total",
    "Писем извлечено из IMAP-ящика (UNSEEN) для приёма",
)
EMAIL_INGESTED = Counter(
    "email_ingested_total",
    "Писем принято в заявки по исходу ingestion",
    ["outcome"],  # created | attached | deduped
)
EMAIL_OVERSIZED = Counter(
    "email_oversized_total",
    "Писем пропущено: размер тела превысил лимит (email_raw_max_bytes)",
)
EMAIL_INGEST_FAILURES = Counter(
    "email_ingest_failures_total",
    "Сбоев приёма письма (ingest/commit) — письмо НЕ помечено обработанным, ретрай",
)
EMAIL_ATTACHMENT_SIZE = Histogram(
    "email_attachment_size_bytes",
    "Размер ПРИНЯТОГО вложения входящего email (только успешно загруженные в kb-files; "
    "oversized отсеяны парсером до приёма и учитываются отдельно — НЕ в этой гистограмме)",
    buckets=_ATTACHMENT_SIZE_BUCKETS,
)


def record_attachment_size(size: int) -> None:
    """Учесть размер принятого (успешно загруженного) вложения. Только число — без ПДн."""
    EMAIL_ATTACHMENT_SIZE.observe(size)


def record_fetched(count: int) -> None:
    """Учесть число извлечённых из ящика писем за проход."""
    if count:
        EMAIL_FETCHED.inc(count)


def record_ingested(*, created: bool, deduped: bool) -> None:
    """Учесть исход ingestion одного письма: created / deduped / attached."""
    outcome = "created" if created else "deduped" if deduped else "attached"
    EMAIL_INGESTED.labels(outcome=outcome).inc()


def record_oversized() -> None:
    """Учесть письмо, пропущенное по превышению лимита размера тела."""
    EMAIL_OVERSIZED.inc()


def record_ingest_failure() -> None:
    """Учесть сбой приёма письма (не помечается обработанным → будет ретрай)."""
    EMAIL_INGEST_FAILURES.inc()
