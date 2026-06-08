"""Тонкий imaplib-адаптер ящика поддержки (E7-4, #146) — реализация `ImapMailbox`.

Своя реализация приёма в контуре РФ (ADR-0005 Реш.3, stdlib `imaplib`, без новых deps).
IMAPS с проверкой сертификата (`ssl.create_default_context` — НЕ отключаем проверку,
анти-паттерн). Провизорно: формат провайдера может уточниться — адаптер за `ImapMailbox`
Protocol, заменяем без правки оркестрации/тестов. Сетевую корректность против живого
сервера валидирует ops (в CI IMAP-сервера нет — тесты на фейке).
"""

from __future__ import annotations

import imaplib
import ssl

from api.config import Settings
from api.email.worker.poll import FetchedMessage


class ImaplibMailbox:
    """Почтовый ящик поверх `imaplib.IMAP4[_SSL]`. Создавать через `connect`."""

    def __init__(self, conn: imaplib.IMAP4) -> None:
        self._conn = conn

    @classmethod
    def connect(cls, settings: Settings) -> ImaplibMailbox:
        """Подключиться, авторизоваться и выбрать папку-источник."""
        conn: imaplib.IMAP4
        if settings.imap_use_ssl:
            conn = imaplib.IMAP4_SSL(
                settings.imap_host, settings.imap_port, ssl_context=ssl.create_default_context()
            )
        else:
            conn = imaplib.IMAP4(settings.imap_host, settings.imap_port)
        conn.login(settings.imap_username, settings.imap_password)
        conn.select(settings.imap_mailbox)
        return cls(conn)

    def fetch_unseen(self, limit: int) -> list[FetchedMessage]:
        """UID SEARCH UNSEEN → до `limit` писем, UID FETCH RFC822."""
        typ, data = self._conn.uid("SEARCH", "UNSEEN")
        if typ != "OK" or not data:
            return []
        ids = data[0]
        if not isinstance(ids, bytes):
            return []
        messages: list[FetchedMessage] = []
        for uid in ids.split()[:limit]:
            ftyp, fetched = self._conn.uid("FETCH", uid.decode(), "(RFC822)")
            if ftyp != "OK":
                continue
            raw = _extract_rfc822(fetched)
            if raw is not None:
                messages.append(FetchedMessage(uid=uid, raw=raw))
        return messages

    def mark_processed(self, uid: bytes, *, move_to: str | None) -> None:
        """Пометить \\Seen и (если задано) перенести в папку: COPY → \\Deleted → expunge."""
        uid_s = uid.decode()
        self._conn.uid("STORE", uid_s, "+FLAGS", "(\\Seen)")
        if move_to:
            self._conn.uid("COPY", uid_s, move_to)
            self._conn.uid("STORE", uid_s, "+FLAGS", "(\\Deleted)")
            self._conn.expunge()

    def close(self) -> None:
        """Закрыть папку и разлогиниться (best-effort на уровне вызывающего)."""
        self._conn.logout()


def _extract_rfc822(parts: list[object]) -> bytes | None:
    """Достать RFC822-тело из ответа imaplib FETCH (кортеж `(meta, payload)`)."""
    for part in parts:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes | bytearray):
            return bytes(part[1])
    return None
