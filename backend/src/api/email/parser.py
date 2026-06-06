"""Чистый парсер входящего email (E7-2, #144).

Без I/O и логгера: разбирает сырое RFC822-письмо в нормализованный `ParsedEmail`.
Доверие к отправителю, резолв requester_id, привязка к реальной заявке и загрузка
вложений в kb-files — НЕ здесь, а в ingestion (#145, ADR-0010 Решение 3). IMAP/сеть —
в воркере (#146).

**malformed-safe (граница недоверенного внешнего ввода):** `parse_email` НИКОГДА не
бросает на любых `bytes` — ошибки разбора сюрфейсятся в `parse_error` (не глотаются),
чтобы IMAP-воркер карантинил письмо, а не падал. ФЗ-152: модуль ничего не логирует —
ПДн (From/тело/вложения) не утекают на этом слое.
"""

from __future__ import annotations

import email
import email.policy
import html
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

# Формат номера заявки — `RH-YYYY-NNNNN` (`tickets/numbering.format_ticket_number`),
# N глобально монотонный (может быть >5 цифр). `\b`-якоря отсекают мусорный
# префикс/суффикс (`XRH-…`/`…00042x`) → меньше риск ложной привязки чужого письма.
_TICKET_NUMBER_RE = re.compile(r"\bRH-\d{4}-\d{5,}\b", re.IGNORECASE)

# HTML-fallback (lossy): сперва вырезаем script/style целиком, затем теги.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_BREAK_RE = re.compile(r"(?i)<br\s*/?>|</(p|div|tr|h[1-6]|li)>")
_TAG_RE = re.compile(r"<[^>]+>")

# Очистка тела: срез по самому раннему из маркеров цитаты/подписи.
_SIGNATURE_RE = re.compile(r"\n-- \n")  # RFC 3676 signature delimiter
_QUOTE_LINE_RE = re.compile(r"^>.*$", re.MULTILINE)
_REPLY_ATTRIB_RES = (
    re.compile(r"^On\b.*\bwrote:\s*$", re.MULTILINE),  # англоязычные клиенты
    re.compile(r"^.*\bписал(?:\(а\)|а)?:\s*$", re.MULTILINE),  # русскоязычные клиенты
)


@dataclass(frozen=True)
class ParsedAttachment:
    filename: str
    content_type: str
    content: bytes
    size: int


@dataclass(frozen=True)
class ParsedEmail:
    from_addr: str
    message_id: str | None
    subject: str
    text_body: str
    ticket_number: str | None
    attachments: tuple[ParsedAttachment, ...]
    oversized_filenames: tuple[str, ...]
    date: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    parse_error: str | None


def extract_ticket_number(subject: str) -> str | None:
    """Извлечь номер заявки `RH-YYYY-NNNNN` из темы (регистронезависимо)."""
    match = _TICKET_NUMBER_RE.search(subject or "")
    return match.group(0).upper() if match else None


def clean_body(text: str) -> str:
    """Срезать цитату/подпись: текст до самого раннего маркера. Чистая, идемпотентная."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    cuts: list[int] = []
    sig = _SIGNATURE_RE.search(normalized)
    if sig is not None:
        cuts.append(sig.start())
    quote = _QUOTE_LINE_RE.search(normalized)
    if quote is not None:
        cuts.append(quote.start())
    for attrib_re in _REPLY_ATTRIB_RES:
        attrib = attrib_re.search(normalized)
        if attrib is not None:
            cuts.append(attrib.start())

    if cuts:
        return normalized[: min(cuts)].strip()
    return normalized.strip()


def _html_to_text(raw_html: str) -> str:
    """Lossy fallback: HTML → текст (только когда нет text/plain). Удаляет
    script/style, переводит блочные теги в перевод строки, снимает теги и сущности."""
    without_scripts = _SCRIPT_STYLE_RE.sub("", raw_html)
    with_breaks = _BLOCK_BREAK_RE.sub("\n", without_scripts)
    stripped = _TAG_RE.sub("", with_breaks)
    return html.unescape(stripped).strip()


def _part_bytes(part: EmailMessage) -> bytes:
    """Сырые байты части (вложения). policy=default → get_content() даёт bytes для
    бинарных; фолбэк на ручное декодирование payload."""
    try:
        content = part.get_content()
    except (LookupError, ValueError, KeyError):
        content = None
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8", "replace")
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def _extract_body_and_attachments(
    msg: EmailMessage, max_attachment_bytes: int | None
) -> tuple[str, tuple[ParsedAttachment, ...], tuple[str, ...]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[ParsedAttachment] = []
    oversized: list[str] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        content_type = part.get_content_type()
        is_attachment = disposition == "attachment" or (
            filename is not None and not content_type.startswith("text/")
        )
        if is_attachment:
            data = _part_bytes(part)
            name = filename or "attachment"
            if max_attachment_bytes is not None and len(data) > max_attachment_bytes:
                oversized.append(name)
                continue
            attachments.append(
                ParsedAttachment(
                    filename=name, content_type=content_type, content=data, size=len(data)
                )
            )
            continue
        if content_type == "text/plain":
            payload = part.get_content()
            plain_parts.append(payload if isinstance(payload, str) else "")
        elif content_type == "text/html":
            payload = part.get_content()
            html_parts.append(payload if isinstance(payload, str) else "")

    if plain_parts:
        body = clean_body("\n".join(plain_parts))
    elif html_parts:
        body = clean_body(_html_to_text("\n".join(html_parts)))
    else:
        body = ""
    return body, tuple(attachments), tuple(oversized)


def parse_email(raw: bytes, *, max_attachment_bytes: int | None = None) -> ParsedEmail:
    """Разобрать сырое письмо. НИКОГДА не бросает: при сбое — `parse_error` заполнен,
    поля best-effort (см. модульный docstring)."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        from_addr = parseaddr(str(msg.get("From", "")))[1]
        message_id = (str(msg.get("Message-ID")).strip() or None) if msg.get("Message-ID") else None
        subject = str(msg.get("Subject", ""))
        date = str(msg.get("Date")) if msg.get("Date") else None
        in_reply_to = str(msg.get("In-Reply-To")).strip() if msg.get("In-Reply-To") else None
        references = tuple(str(msg.get("References", "")).split())
        body, attachments, oversized = _extract_body_and_attachments(msg, max_attachment_bytes)
        return ParsedEmail(
            from_addr=from_addr,
            message_id=message_id,
            subject=subject,
            text_body=body,
            ticket_number=extract_ticket_number(subject),
            attachments=attachments,
            oversized_filenames=oversized,
            date=date,
            in_reply_to=in_reply_to,
            references=references,
            parse_error=None,
        )
    except Exception as exc:  # noqa: BLE001 — граница недоверенного ввода: не ронять воркер; ошибка сюрфейсится в parse_error, не глотается
        return ParsedEmail(
            from_addr="",
            message_id=None,
            subject="",
            text_body="",
            ticket_number=None,
            attachments=(),
            oversized_filenames=(),
            date=None,
            in_reply_to=None,
            references=(),
            parse_error=type(exc).__name__,
        )
