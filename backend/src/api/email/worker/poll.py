r"""Оркестрация IMAP-приёма (E7-4, #146) — чистая, без прямого знания imaplib.

`ImapMailbox` Protocol изолирует сеть (в тестах — фейк, без сервера). `poll_and_ingest`
тянет UNSEEN-письма и для КАЖДОГО независимо: проверка размера → парсер #144 →
`ingest_email` (#145) → **commit** → `mark_processed` (\Seen + опц. перенос). Решение
Архитектора Д4 — **per-message commit**: каждое письмо самостоятельная единица с внешним
side-effect (`mark_processed`); сбой одного (rollback, без mark) не трогает остальные,
а порядок commit→mark даёт at-least-once (лучше дубль, чем потеря заявки).

Идемпотентность повтора — на ядре #145 (дедуп по Message-ID). Письмо БЕЗ Message-ID при
сбое mark_processed теоретически даст дубль-заявку (принятый best-effort из #145). ФЗ-152:
тело/From/тема в логи не попадают — только счётчики/operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from api.email import metrics
from api.email.ingestion import ingest_email
from api.email.parser import parse_email
from api.observability.logging import get_logger

_logger = get_logger("email.worker")


@dataclass(frozen=True)
class FetchedMessage:
    """Сырое письмо из ящика: серверный uid (не ПДн) + RFC822-байты."""

    uid: bytes
    raw: bytes


class ImapMailbox(Protocol):
    """Контракт почтового ящика (реальный — imaplib; в тестах — фейк)."""

    def fetch_unseen(self, limit: int) -> list[FetchedMessage]:
        """Вернуть до `limit` непрочитанных писем (UNSEEN)."""
        ...

    def mark_processed(self, uid: bytes, *, move_to: str | None) -> None:
        """Пометить письмо \\Seen и (если задано) перенести в папку `move_to`."""
        ...


@dataclass(frozen=True)
class PollResult:
    fetched: int
    ingested: int
    skipped_oversized: int
    failed: int


async def poll_and_ingest(
    session: AsyncSession,
    mailbox: ImapMailbox,
    *,
    batch_limit: int,
    raw_max_bytes: int,
    attachment_max_bytes: int,
    processed_mailbox: str | None,
) -> PollResult:
    """Один проход приёма. Per-message commit; сбой письма изолирован (best-effort)."""
    messages = mailbox.fetch_unseen(batch_limit)
    metrics.record_fetched(len(messages))
    if len(messages) >= batch_limit:
        # no-silent-caps: ящик мог содержать больше — остаток разберёт следующий проход.
        _logger.warning("imap poll hit batch_limit=%d — more may remain", batch_limit)

    ingested = skipped = failed = 0
    for msg in messages:
        # Anti-DoS: при IMAP-приёме нет HTTP-шлюза (#145), лимит тела проверяем здесь.
        if len(msg.raw) > raw_max_bytes:
            metrics.record_oversized()
            skipped += 1
            # Помечаем обработанным: повтор не поможет (письмо всегда oversized) — не poison.
            _safe_mark(mailbox, msg.uid, processed_mailbox)
            _logger.warning("imap message skipped: exceeds size limit")
            continue

        # Парсер #144 malformed-safe (не бросает; parse_error → заявка с пометкой).
        parsed = parse_email(msg.raw, max_attachment_bytes=attachment_max_bytes)
        # KNOWN-LIMITATION (#139/#77): platform/kb-files клиенты НЕ прокидываются из
        # воркера — фабрики этих клиентов FastAPI-зависимости (async-генераторы),
        # переиспользуемы только в request-цикле. До общей не-FastAPI фабрики (#139) и
        # боевого m2m-токена (#77) приём из IMAP резолвит отправителя в sentinel и
        # откладывает вложения (как при выключенной интеграции). Эндпоинт #145 их
        # прокидывает; паритет воркера включится с #139.
        try:
            result = await ingest_email(session, parsed, platform_client=None, kb_files_client=None)
            await session.commit()
        except Exception:
            # Сбой ingest/commit (БД/сеть): откат, НЕ помечаем обработанным → ретрай на
            # следующем проходе. Перманентный сбой виден через email_ingest_failures_total
            # (сигнал для алертинга); dead-letter — отдельный тикет, не #146.
            await session.rollback()
            metrics.record_ingest_failure()
            failed += 1
            _logger.warning("imap message ingest failed — will retry next poll")
            continue

        metrics.record_ingested(created=result.created, deduped=result.deduped)
        ingested += 1
        # commit прошёл → теперь безопасно пометить обработанным (at-least-once).
        _safe_mark(mailbox, msg.uid, processed_mailbox)

    return PollResult(
        fetched=len(messages), ingested=ingested, skipped_oversized=skipped, failed=failed
    )


def _safe_mark(mailbox: ImapMailbox, uid: bytes, processed_mailbox: str | None) -> None:
    """Пометить письмо обработанным; сбой IMAP-пометки не валит проход.

    Письмо уже в БД (commit прошёл). Если пометка не удалась — при следующем проходе
    письмо снова UNSEEN → повторный приём, дедуп по Message-ID спасёт (#145; письмо без
    Message-ID — принятый best-effort риск дубля)."""
    try:
        mailbox.mark_processed(uid, move_to=processed_mailbox or None)
    except Exception:
        _logger.warning("imap mark_processed failed — message stays UNSEEN, dedup on re-poll")
