"""Unit-тесты `ImaplibMailbox` (E7-4, #146) с фейковым imaplib-соединением.

Без сети: инъекция fake-conn в конструктор. Покрывают разбор SEARCH/FETCH, пометку
\\Seen и перенос (COPY → \\Deleted → expunge). `connect()` (реальный сокет/TLS) — не
unit-тестируется (ops валидирует против живого сервера).
"""

from __future__ import annotations

from typing import Any

from api.email.worker.imap_client import ImaplibMailbox, _extract_rfc822


class _FakeConn:
    def __init__(
        self, search: tuple[str, list[Any]], fetch: dict[str, tuple[str, list[Any]]]
    ) -> None:
        self._search = search
        self._fetch = fetch
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.expunged = 0

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.calls.append((command, args))
        if command == "SEARCH":
            return self._search
        if command == "FETCH":
            return self._fetch[args[0]]
        return ("OK", [b""])

    def expunge(self) -> tuple[str, list[Any]]:
        self.expunged += 1
        return ("OK", [b""])

    def logout(self) -> tuple[str, list[Any]]:
        self.calls.append(("LOGOUT", ()))
        return ("BYE", [b""])


def _mailbox(
    search: tuple[str, list[Any]], fetch: dict[str, tuple[str, list[Any]]]
) -> tuple[ImaplibMailbox, _FakeConn]:
    conn = _FakeConn(search, fetch)
    return ImaplibMailbox(conn), conn  # type: ignore[arg-type]  # fake реализует нужный минимум


def test_fetch_unseen_parses_uids_and_bodies() -> None:
    mb, _ = _mailbox(
        ("OK", [b"10 11"]),
        {
            "10": ("OK", [(b"10 (RFC822 {3}", b"AAA")]),
            "11": ("OK", [(b"11 (RFC822 {3}", b"BBB")]),
        },
    )
    msgs = mb.fetch_unseen(50)
    assert [(m.uid, m.raw) for m in msgs] == [(b"10", b"AAA"), (b"11", b"BBB")]


def test_fetch_unseen_respects_limit() -> None:
    mb, _ = _mailbox(
        ("OK", [b"10 11 12"]),
        {"10": ("OK", [(b"x", b"A")]), "11": ("OK", [(b"x", b"B")])},
    )
    assert len(mb.fetch_unseen(2)) == 2


def test_fetch_unseen_empty_on_non_ok_or_garbage() -> None:
    assert _mailbox(("NO", [b""]), {})[0].fetch_unseen(50) == []
    assert _mailbox(("OK", [None]), {})[0].fetch_unseen(50) == []  # ids не bytes


def test_fetch_skips_message_without_payload() -> None:
    mb, _ = _mailbox(("OK", [b"10"]), {"10": ("OK", [b"no-tuple-payload"])})
    assert mb.fetch_unseen(50) == []


def test_mark_processed_seen_only() -> None:
    mb, conn = _mailbox(("OK", [b""]), {})
    mb.mark_processed(b"10", move_to=None)
    assert ("STORE", ("10", "+FLAGS", "(\\Seen)")) in conn.calls
    assert conn.expunged == 0  # без переноса — без expunge


def test_mark_processed_moves_to_folder() -> None:
    mb, conn = _mailbox(("OK", [b""]), {})
    mb.mark_processed(b"10", move_to="Processed")
    commands = [c[0] for c in conn.calls]
    assert commands == ["STORE", "COPY", "STORE"]  # \Seen, COPY, \Deleted
    assert ("COPY", ("10", "Processed")) in conn.calls
    assert conn.expunged == 1


def test_close_logs_out() -> None:
    mb, conn = _mailbox(("OK", [b""]), {})
    mb.close()
    assert ("LOGOUT", ()) in conn.calls


def test_extract_rfc822_variants() -> None:
    assert _extract_rfc822([(b"meta", b"body")]) == b"body"
    assert _extract_rfc822([(b"meta", bytearray(b"ba"))]) == b"ba"
    assert _extract_rfc822([b"flat", (b"only-one-elem",)]) is None
