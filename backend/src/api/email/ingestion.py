"""Ingestion входящего email (E7-3, #145) — оркестрация поверх парсера #144.

Политика приёма (ADR-0010 Решения 1/3/4):
- **Идемпотентность** по `Message-ID` (дедуп повторно доставленных писем).
- **Привязка** к активной заявке по номеру в теме; иначе/CLOSED — новая заявка
  (channel=EMAIL, `description=""`, тело — в первом сообщении: решение Архитектора,
  email-native, без дублирования ПДн).
- **Sender НЕ доверяем** (anti-spoofing): requester_id — резолв через platform по
  email (config-gated, БЕЗ кеша — email это ПДн), иначе sentinel `EMAIL_SENDER_ACTOR_ID`.
  Для ответа автор сообщения — тоже резолв/sentinel (не доверяем, что отправитель =
  исходный заявитель; requester заявки НЕ меняется). `is_internal=False` всегда (NFR-1.3).
- **Вложения** → kb-files (config-gated); выключено/сбой → не теряем письмо, помечаем.

I/O-слой: работает с переданной сессией и (config-gated) клиентами. Worker #146
зовёт `ingest_email` напрямую; endpoint #145(PR-B) — тонкая обёртка. ФЗ-152: логи —
только счётчики/operation, без тела/from/filename.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.system_actors import EMAIL_SENDER_ACTOR_ID
from api.clients.errors import ExternalServiceError
from api.clients.kb_files import KbFilesClient
from api.clients.platform import PlatformClient
from api.email import metrics
from api.email.parser import ParsedAttachment, ParsedEmail
from api.observability.logging import get_logger
from api.tickets.messages import TicketMessage
from api.tickets.models import Ticket
from api.tickets.repository import TicketRepository

_logger = get_logger("email.ingestion")

_DEFAULT_SUBJECT = "Обращение по email"
_SUBJECT_MAX = 300


@dataclass(frozen=True)
class IngestResult:
    ticket: Ticket
    created: bool
    deduped: bool


async def ingest_email(
    session: AsyncSession,
    parsed: ParsedEmail,
    *,
    platform_client: PlatformClient | None,
    kb_files_client: KbFilesClient | None,
) -> IngestResult:
    """Принять разобранное письмо. Дедуп → привязка/создание. Не бросает на дубле.

    Дедуп — по `Message-ID`; письмо БЕЗ Message-ID (`message_id is None`) не дедупится
    (best-effort) — повторная доставка такого письма может создать второй экземпляр
    (редко: relay обычно проставляет Message-ID; частичный uniq — только для NOT NULL)."""
    repo = TicketRepository(session)

    # 1. Идемпотентность: уже принятое письмо (Message-ID) → no-op.
    if parsed.message_id:
        seen = await repo.find_message_by_email_id(parsed.message_id)
        if seen is not None:
            return await _result_for_message(session, seen)

    # 2. Резолв отправителя (НЕ доверяем From).
    requester_id = await _resolve_requester(parsed.from_addr, platform_client)
    # 3. Вложения (config-gated).
    attachments, deferred = await _upload_attachments(parsed.attachments, kb_files_client)
    # 4. Привязка к активной заявке по номеру.
    target = None
    if parsed.ticket_number:
        target = await repo.find_active_by_number(parsed.ticket_number)

    if target is not None:
        try:
            await repo.add_email_message(
                target.id,
                author_id=requester_id,
                body=parsed.text_body,
                attachments=attachments,
                email_message_id=parsed.message_id,
            )
        except IntegrityError:
            return await _recover_dedup(session, repo, parsed)
        return IngestResult(target, created=False, deduped=False)

    # 5. Новая заявка (нет номера / не найдена / CLOSED).
    ticket = await repo.create_from_email(
        subject=_subject(parsed),
        requester_id=requester_id,
        custom_fields=_email_custom_fields(parsed, deferred),
    )
    try:
        await repo.add_email_message(
            ticket.id,
            author_id=requester_id,
            body=parsed.text_body,
            attachments=attachments,
            email_message_id=parsed.message_id,
        )
    except IntegrityError:
        return await _recover_dedup(session, repo, parsed)
    return IngestResult(ticket, created=True, deduped=False)


async def _resolve_requester(from_addr: str, platform_client: PlatformClient | None) -> uuid.UUID:
    """requester_id из platform по email (config-gated, без кеша — ПДн) либо sentinel."""
    if platform_client is not None and from_addr:
        user = await platform_client.get_user_by_email(from_addr)
        if user is not None:
            return user.id
    return EMAIL_SENDER_ACTOR_ID


async def _upload_attachments(
    attachments: tuple[ParsedAttachment, ...], kb_files_client: KbFilesClient | None
) -> tuple[list[str], dict[str, Any] | None]:
    """Загрузить вложения в kb-files. Выключено → отложить (пометка). Сбой upload —
    per-attachment best-effort (письмо не теряем). Возвращает (file_ids, deferred-инфо)."""
    if not attachments:
        return [], None
    if kb_files_client is None:
        _logger.warning("email attachments deferred: kb-files off (count=%d)", len(attachments))
        return [], {"deferred_count": len(attachments), "reason": "kb_files_not_configured"}

    file_ids: list[str] = []
    failed = 0
    for att in attachments:
        try:
            stored = await kb_files_client.upload(
                filename=att.filename, content_type=att.content_type, content=att.content
            )
            file_ids.append(stored.id)
            metrics.record_attachment_size(att.size)  # #151: размер принятого вложения
        except ExternalServiceError:
            # Тело/имя не логируем (ФЗ-152) — только факт сбоя.
            failed += 1
    if failed:
        _logger.warning("email attachments partially failed: count=%d", failed)
        return file_ids, {"failed_count": failed}
    return file_ids, None


def _subject(parsed: ParsedEmail) -> str:
    return ((parsed.subject or "").strip() or _DEFAULT_SUBJECT)[:_SUBJECT_MAX]


def _email_custom_fields(parsed: ParsedEmail, deferred: dict[str, Any] | None) -> dict[str, Any]:
    """Метаданные письма на заявке. from_addr — ПДн внутреннего контура (оператор
    привязывает заявителя вручную при sentinel-резолве)."""
    cf: dict[str, Any] = {"email_from": parsed.from_addr}
    if parsed.message_id:
        cf["email_message_id"] = parsed.message_id
    if parsed.oversized_filenames:
        cf["email_oversized_attachments"] = list(parsed.oversized_filenames)
    if deferred is not None:
        cf["email_attachments_deferred"] = deferred
    if parsed.parse_error is not None:
        cf["email_parse_error"] = parsed.parse_error
    return cf


async def _recover_dedup(
    session: AsyncSession, repo: TicketRepository, parsed: ParsedEmail
) -> IngestResult:
    """Гонка на частичном uniq email_message_id: откат + возврат победившего письма."""
    await session.rollback()
    if parsed.message_id:
        seen = await repo.find_message_by_email_id(parsed.message_id)
        if seen is not None:
            return await _result_for_message(session, seen)
    # Недостижимо: IntegrityError бывает только при непустом конфликтующем Message-ID.
    raise RuntimeError("email ingestion dedup recovery failed")  # pragma: no cover


async def _result_for_message(session: AsyncSession, message: TicketMessage) -> IngestResult:
    ticket = await session.get(Ticket, message.ticket_id)
    if ticket is None:  # pragma: no cover — FK гарантирует наличие
        raise RuntimeError("ingested email message has no ticket")
    return IngestResult(ticket, created=False, deduped=True)
