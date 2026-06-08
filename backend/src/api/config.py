"""Application settings via pydantic-settings.

Все настройки загружаются из env (или `.env` файла для local dev).
Префикс env-переменных: `KBS_*` (`KBS_DATABASE_URL`, `KBS_DATABASE_POOL_SIZE`, ...).

На bootstrap'е (#2) — только DB-related поля. Расширится по мере появления
Redis (E4), external API клиентов (E3), Keycloak (E3) и т.д.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Глобальные настройки сервиса."""

    model_config = SettingsConfigDict(
        env_prefix="KBS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://kbsupport:devpass@localhost:5432/kbsupport",
        description=(
            "PostgreSQL async DSN (asyncpg driver). "
            "TLS на этом этапе не enforce'ится; для prod добавить sslmode=require "
            "+ sslrootcert через параметры query string."
        ),
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_max_overflow: int = Field(default=20, ge=0, le=200)
    database_echo: bool = Field(
        default=False,
        description="SQLAlchemy echo для debug. В production — всегда False.",
    )
    history_retention_days: int = Field(
        default=1825,
        ge=1,
        description=(
            "Срок хранения TicketHistory (NFR-1.4 — 5 лет = 1825 дней). "
            "Фактический cleanup-воркер — отдельный Issue в E8; здесь только "
            "конфигурируемая политика."
        ),
    )
    log_level: str = Field(
        default="INFO",
        description="Уровень JSON-логирования (DEBUG/INFO/WARNING/ERROR).",
    )
    chat_transcript_max_turns: int = Field(
        default=200,
        ge=1,
        le=5000,
        description=(
            "Максимум реплик в transcript эскалации из чата (E3-1, #69). Защита "
            "от злоупотребления размером тела; превышение → 422."
        ),
    )
    email_raw_max_bytes: int = Field(
        default=26 * 1024 * 1024,
        ge=1,
        description=(
            "Максимальный размер декодированного RFC822-письма в байтах при приёме "
            "через POST /tickets/from-email (E7-3, #145). Защита от memory-DoS на "
            "входе шлюза; превышение → 422. Лимит на тело письма целиком (не на "
            "отдельные вложения — для них email_attachment_max_bytes)."
        ),
    )
    email_attachment_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1,
        description=(
            "Максимальный размер одного вложения входящего email в байтах (E7-3, "
            "#145). Передаётся в парсер; вложения сверх лимита отсекаются "
            "(email_oversized_attachments в custom_fields), письмо принимается."
        ),
    )
    # --- Keycloak Bearer JWT (#29). Пустой auth_jwks_url → auth не сконфигурирован
    # (fail-closed 401). Реалм/issuer/audience задаются в окружении деплоя. ---
    auth_jwks_url: str = Field(
        default="",
        description="URL JWKS Keycloak (.../protocol/openid-connect/certs).",
    )
    auth_issuer: str = Field(default="", description="Ожидаемый iss токена (пусто → не проверять).")
    auth_audience: str = Field(
        default="", description="Ожидаемый aud токена (пусто → не проверять)."
    )
    auth_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    auth_leeway: int = Field(default=0, ge=0, description="Допуск по времени (сек) для exp/nbf.")
    auth_jwks_cache_ttl: int = Field(
        default=300, ge=1, description="TTL кеша JWKS (сек) до принудительного рефреша."
    )

    # --- HTTP-клиенты к соседям (AT-003, E3-2). Параметры resilience и кеша.
    # Конкретные base-URL соседей задаются в их клиентах (#71/#72), не здесь. ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="URL Redis для кеша HTTP-клиентов (E3-2). Пусто/недоступен → кеш off.",
    )
    client_timeout_seconds: float = Field(
        default=5.0, gt=0, description="Таймаут одного HTTP-вызова к соседу (сек)."
    )
    client_retry_attempts: int = Field(
        default=3, ge=1, le=10, description="Всего попыток вызова (включая первую)."
    )
    client_retry_base_delay: float = Field(
        default=0.1, gt=0, description="Базовая задержка backoff (сек): base * 2**(n-1)."
    )
    client_retry_max_delay: float = Field(
        default=2.0, gt=0, description="Потолок задержки backoff (сек)."
    )
    client_breaker_failure_threshold: int = Field(
        default=5, ge=1, description="Подряд ошибок до открытия circuit breaker."
    )
    client_breaker_reset_timeout: float = Field(
        default=30.0, gt=0, description="Сек до перехода OPEN → HALF_OPEN (пробный вызов)."
    )
    client_cache_ttl_seconds: int = Field(
        default=60, ge=1, description="TTL по умолчанию для кеша ответов соседей (сек)."
    )

    # --- rehome.one platform API (E3-3, #71). Провизорный контракт ADR-0006. ---
    platform_api_base_url: str = Field(
        default="http://localhost:8081",
        description="Базовый URL rehome.one platform API (контекст заявителя).",
    )
    platform_api_token: str = Field(
        default="",
        description=(
            "Плейсхолдер m2m-токена для StaticTokenProvider (dev/test). Реальный "
            "ClientCredentials провайдер — #77 (ждёт провижининга realm)."
        ),
    )
    platform_cache_ttl_seconds: int = Field(
        default=300,
        ge=1,
        description="TTL кеша справочных данных платформы (сек). Read-only, ПДн.",
    )

    # --- kb-search возврат ответа оператора (E3-4, #72). Провизорный контракт
    # ADR-0006 Решение 3. ПУСТОЙ kb_search_api_token = функция выключена (gate):
    # без реального m2m-токена (#77) фоновая доставка не планируется. ---
    kb_search_api_base_url: str = Field(
        default="http://localhost:8082",
        description="Базовый URL kb-search API (возврат ответа в chat-session).",
    )
    kb_search_api_token: str = Field(
        default="",
        description=(
            "m2m-токен для StaticTokenProvider (dev/test). ПУСТО → возврат ответа "
            "в чат ВЫКЛЮЧЕН. Реальный ClientCredentials — #77."
        ),
    )

    # --- kb-wiki (E6-5, #129, ADR-0009 Решение 3). Провизорный контракт; read-only
    # (проверка существования статьи по slug). ПУСТОЙ kb_wiki_api_token = интеграция
    # выключена (slug принимается без валидации; инертно до #77). ---
    kb_wiki_api_base_url: str = Field(
        default="http://localhost:8083",
        description="Базовый URL kb-wiki API (статьи базы знаний, read-only).",
    )
    kb_wiki_api_token: str = Field(
        default="",
        description=(
            "m2m-токен для StaticTokenProvider (dev/test). ПУСТО → kb-wiki выключен "
            "(slug не валидируется). Реальный ClientCredentials — #77."
        ),
    )

    # --- kb-files (E7-1, #143, ADR-0010 Решение 4). Загрузка вложений email/веб-формы
    # в MinIO по API (НЕ shared bucket). Провизорный контракт. ПУСТОЙ kb_files_api_token =
    # интеграция выключена (фабрика потребителя #145 вернёт None; upload не зовётся;
    # инертно до #77). ---
    kb_files_api_base_url: str = Field(
        default="http://localhost:8084",
        description="Базовый URL kb-files API (загрузка вложений заявок в MinIO).",
    )
    kb_files_api_token: str = Field(
        default="",
        description=(
            "m2m-токен для StaticTokenProvider (dev/test). ПУСТО → kb-files выключен "
            "(вложения не загружаются). Реальный ClientCredentials — #77."
        ),
    )

    # --- SLA-воркер (E4-6, #90, ADR-0007 Решение 1). Dramatiq-actor проактивно
    # сканирует БД по дедлайнам и дёргает breach-хук (seam под эскалацию E5/#18).
    # ПУСТОЙ sla_worker_broker_url = выключено (StubBroker, actor инертен) — тот же
    # gate-приём, что у platform/kb-search до #77. Боевой путь — после ops
    # (broker/worker, пересекается с #79). Read-side breach (#89) работает независимо. ---
    sla_worker_broker_url: str = Field(
        default="",
        description=(
            "URL Redis-broker для Dramatiq SLA-воркера. ПУСТО → StubBroker, actor "
            "инертен (broker/worker поднимает ops). Read-side breach не зависит от него."
        ),
    )
    sla_scan_batch_limit: int = Field(
        default=500,
        ge=1,
        description=(
            "Максимум заявок, обрабатываемых за один проход скана SLA-дедлайнов. "
            "Защита от чрезмерной выборки; выборка детерминирована (ORDER BY due_at)."
        ),
    )

    # --- time_based-автоматизация (E5, #110, ADR-0008 Реш.6). Dramatiq-actor
    # `check_time_based_rules` сканирует БД по временным условиям правил и применяет
    # действия. Config-gate — ТОТ ЖЕ `sla_worker_broker_url` (единый Dramatiq-broker на
    # сервис, оба actor'а); пусто → StubBroker → actor инертен. Боевой путь — после ops
    # (#79). Источник истины — БД (NFR-3.2), восстановление сканом, не из памяти. ---
    automation_scan_batch_limit: int = Field(
        default=500,
        ge=1,
        description=(
            "Максимум заявок за один проход скана time_based-правил (на правило). Защита "
            "от чрезмерной выборки; выборка детерминирована (ORDER BY updated_at, id)."
        ),
    )

    # --- IMAP-приём входящего email (E7-4, #146, ADR-0005 Реш.3 / ADR-0010 Реш.1).
    # Dramatiq-actor `poll_inbox` тянет UNSEEN-письма из ящика поддержки и отдаёт в
    # ingestion (#145). Двойной gate: единый `sla_worker_broker_url` (StubBroker →
    # actor не enqueue'ится) И ПУСТОЙ `imap_host` (проход — no-op, даже при поднятом
    # broker). Боевой путь — после ops (broker/worker #79 + IMAP-креды). ---
    imap_host: str = Field(
        default="",
        description="Хост IMAP-сервера ящика поддержки. ПУСТО → приём выключен (no-op проход).",
    )
    imap_port: int = Field(default=993, ge=1, le=65535, description="Порт IMAP (993 = IMAPS).")
    imap_username: str = Field(default="", description="Логин IMAP (из секретов окружения).")
    imap_password: str = Field(default="", description="Пароль IMAP (из секретов; не логируется).")
    imap_mailbox: str = Field(default="INBOX", description="Папка-источник входящих писем.")
    imap_use_ssl: bool = Field(
        default=True,
        description="IMAPS с проверкой сертификата (create_default_context). НЕ отключать в проде.",
    )
    imap_processed_mailbox: str = Field(
        default="",
        description=(
            "Папка, КУДА переносить обработанное письмо после ingest (Д1). ПУСТО → только "
            "пометка \\Seen без переноса."
        ),
    )
    imap_poll_batch_limit: int = Field(
        default=50,
        ge=1,
        description=(
            "Максимум писем за один проход poll_inbox. Защита от чрезмерной выборки; при "
            "достижении лимита — WARN (остаток разберёт следующий проход)."
        ),
    )

    # --- SMTP-отправка ответа оператора на EMAIL-заявку (E7-5, #147, FR-2.3,
    # ADR-0010 Реш.1). fire-after BackgroundTasks (как #72); config-gate по ПУСТОМУ
    # smtp_host (инертно до ops). smtp_from_address ДОЛЖЕН совпадать с ящиком приёма
    # IMAP (#146), иначе ответы заявителя вернутся не туда. Durable — follow-up #79. ---
    smtp_host: str = Field(
        default="",
        description="Хост SMTP-relay. ПУСТО → отправка ответов по email выключена.",
    )
    smtp_port: int = Field(default=587, ge=1, le=65535, description="Порт SMTP (587 = submission).")
    smtp_username: str = Field(default="", description="Логин SMTP (из секретов окружения).")
    smtp_password: str = Field(default="", description="Пароль SMTP (из секретов; не логируется).")
    smtp_use_tls: bool = Field(
        default=True,
        description="STARTTLS с проверкой сертификата (create_default_context). НЕ отключать.",
    )
    smtp_from_address: str = Field(
        default="",
        description="From исходящих писем (служебный адрес поддержки = ящик приёма IMAP #146).",
    )

    # --- Уведомления push/SMS (E7-9, #150, ADR-0010 Реш.5) — config-gated SEAM'ы.
    # ПУСТОЙ токен = канал выключен (intent-log без ПДн, не планируется). Боевая
    # доставка (Exolve SMS + push-провайдер) + резолв получателя — follow-up #161
    # после ops (creds) и #77 (m2m). Базовые URL/from — в #161 (здесь не читаются). ---
    sms_api_token: str = Field(
        default="",
        description="Токен SMS-провайдера (Exolve). ПУСТО → SMS-канал выключен (seam, #161).",
    )
    push_api_token: str = Field(
        default="",
        description="Токен push-провайдера. ПУСТО → push-канал выключен (seam, #161).",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached Settings instance.

    `lru_cache` гарантирует один Settings объект на процесс, чтобы
    pydantic-settings не парсил env при каждом вызове.
    """
    return Settings()
