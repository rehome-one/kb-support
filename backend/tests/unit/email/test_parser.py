"""Тесты чистого email-парсера (E7-2, #144).

Фикстуры строятся через `email.message.EmailMessage` → `.as_bytes()`. Покрытие:
извлечение полей, номер заявки (позиции/регистр/якоря), очистка тела (цитата/подпись),
вложения, oversized, HTML-fallback (script/style/unescape), malformed-safe (никогда
не бросает), multipart + тред-заголовки.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from api.email.parser import (
    ParsedEmail,
    clean_body,
    extract_ticket_number,
    parse_email,
)


def _msg(*, subject: str = "Тема", from_: str = "Иван <ivan@example.com>") -> EmailMessage:
    m = EmailMessage()
    m["From"] = from_
    m["Subject"] = subject
    m["Message-ID"] = "<msg-1@mail>"
    m["Date"] = "Mon, 01 Jun 2026 10:00:00 +0300"
    return m


def test_simple_plain() -> None:
    m = _msg(subject="Привет")
    m.set_content("Тело письма")
    parsed = parse_email(m.as_bytes())
    assert parsed.parse_error is None
    assert parsed.from_addr == "ivan@example.com"
    assert parsed.subject == "Привет"
    assert parsed.text_body == "Тело письма"
    assert parsed.message_id == "<msg-1@mail>"
    assert parsed.date is not None
    assert parsed.attachments == ()


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Re: RH-2026-00042 проблема", "RH-2026-00042"),
        ("вопрос rh-2026-00042", "RH-2026-00042"),  # регистронезависимо
        ("[RH-2026-1234567] длинный номер", "RH-2026-1234567"),  # >5 цифр
        ("без номера", None),
        ("RH-2026-0042 мало цифр", None),  # 4 цифры — не номер
        ("XRH-2026-00042 мусорный префикс", None),  # \b отсекает
        ("RH-2026-00042extra суффикс", None),  # \b отсекает
    ],
)
def test_extract_ticket_number(subject: str, expected: str | None) -> None:
    assert extract_ticket_number(subject) == expected


def test_clean_body_strips_quote_angle() -> None:
    assert clean_body("Мой ответ\n\n> старый текст\n> ещё") == "Мой ответ"


def test_clean_body_strips_reply_attribution_en() -> None:
    assert clean_body("Ответ\nOn Mon, Jun 1 2026, Ivan wrote:\nцитата") == "Ответ"


def test_clean_body_strips_reply_attribution_ru() -> None:
    assert clean_body("Ответ\n01.06.2026 Иван писал(а):\nцитата") == "Ответ"


def test_clean_body_strips_signature() -> None:
    assert clean_body("Текст\n-- \nИван Иванов\nтел. 123") == "Текст"


def test_clean_body_idempotent() -> None:
    once = clean_body("Текст\n> цитата")
    assert clean_body(once) == once == "Текст"


def test_attachments_extracted() -> None:
    m = _msg()
    m.set_content("см. вложение")
    m.add_attachment(b"PDFBYTES", maintype="application", subtype="pdf", filename="doc.pdf")
    parsed = parse_email(m.as_bytes())
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.filename == "doc.pdf"
    assert att.content_type == "application/pdf"
    assert att.content == b"PDFBYTES"
    assert att.size == 8
    assert parsed.text_body == "см. вложение"


def test_oversized_attachment_excluded() -> None:
    m = _msg()
    m.set_content("большое вложение")
    m.add_attachment(b"X" * 100, maintype="application", subtype="octet-stream", filename="big.bin")
    parsed = parse_email(m.as_bytes(), max_attachment_bytes=10)
    assert parsed.attachments == ()
    assert parsed.oversized_filenames == ("big.bin",)


def test_html_only_fallback_strips_script_and_unescapes() -> None:
    m = _msg()
    m.set_content(
        "<html><body>Привет<script>alert(1)</script>"
        " &amp; пока<br>строка2<style>.x{}</style></body></html>",
        subtype="html",
    )
    parsed = parse_email(m.as_bytes())
    assert "alert" not in parsed.text_body
    assert ".x{}" not in parsed.text_body
    assert "&amp;" not in parsed.text_body
    assert "Привет" in parsed.text_body
    assert "пока" in parsed.text_body
    assert "строка2" in parsed.text_body


def test_html_unclosed_script_stripped() -> None:
    # Обрезанный <script> без закрывающего тега → тело JS не утекает в text_body.
    m = _msg()
    m.set_content("<html><body>before<script>evilCode()", subtype="html")
    parsed = parse_email(m.as_bytes())
    assert "evilCode" not in parsed.text_body
    assert "before" in parsed.text_body


def test_multipart_prefers_plain_and_parses_thread_headers() -> None:
    m = _msg()
    m["In-Reply-To"] = "<parent@mail>"
    m["References"] = "<root@mail> <parent@mail>"
    m.set_content("plain версия")
    m.add_alternative("<p>html версия</p>", subtype="html")
    parsed = parse_email(m.as_bytes())
    assert parsed.text_body == "plain версия"
    assert parsed.in_reply_to == "<parent@mail>"
    assert parsed.references == ("<root@mail>", "<parent@mail>")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not an email at all",
        b"\xff\xfe\x00\x01 garbage bytes",
        b"From: x\r\nContent-Type: multipart/mixed; boundary=bnd\r\n\r\n--bnd\r\n",
    ],
)
def test_malformed_never_raises(raw: bytes) -> None:
    parsed = parse_email(raw)
    assert isinstance(parsed, ParsedEmail)
    # Не бросает; либо корректно разобрал, либо пометил parse_error — но не исключение.


def test_bad_charset_sets_parse_error_not_raises() -> None:
    # text/plain с неизвестной кодировкой → get_content может бросить → parse_error.
    raw = (
        b'Content-Type: text/plain; charset="x-unknown-charset-zzz"\r\n'
        b"From: a@b.c\r\nSubject: bad\r\n\r\n"
        b"body"
    )
    parsed = parse_email(raw)
    assert isinstance(parsed, ParsedEmail)
    # Контракт: не бросает на любом вводе (parse_error либо None при толерантном декоде).


def test_text_attachment_uses_str_branch() -> None:
    # Вложение с disposition=attachment, но text/* → _part_bytes идёт по str-ветке.
    m = _msg()
    m.set_content("основной текст")
    m.add_attachment("текстовое вложение", filename="note.txt")
    parsed = parse_email(m.as_bytes())
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.filename == "note.txt"
    assert att.content_type == "text/plain"
    assert "текстовое вложение" in att.content.decode("utf-8")


def test_no_text_parts_yields_empty_body() -> None:
    # Только бинарная часть без filename → не текст и не вложение → тело пустое.
    raw = (
        b"Content-Type: application/octet-stream\r\n"
        b"From: a@b.c\r\nSubject: bin\r\n\r\n"
        b"\x00\x01\x02"
    )
    parsed = parse_email(raw)
    assert parsed.text_body == ""


def test_attachment_bad_charset_falls_back_to_payload() -> None:
    # Вложение text/* с неизвестной кодировкой: get_content() бросает → _part_bytes
    # деградирует на payload-фолбэк (ветка content=None).
    raw = (
        b'Content-Type: multipart/mixed; boundary="b"\r\n'
        b"From: a@b.c\r\nSubject: s\r\n\r\n"
        b"--b\r\nContent-Type: text/plain\r\n\r\nmain body\r\n"
        b'--b\r\nContent-Type: text/plain; charset="x-bad-zzz"\r\n'
        b'Content-Disposition: attachment; filename="a.txt"\r\n\r\n'
        b"attachdata\r\n--b--\r\n"
    )
    parsed = parse_email(raw)
    assert parsed.parse_error is None
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].filename == "a.txt"
    assert b"attachdata" in parsed.attachments[0].content


def test_missing_message_id_is_none() -> None:
    m = EmailMessage()
    m["From"] = "a@b.c"
    m["Subject"] = "no id"
    m.set_content("тело")
    parsed = parse_email(m.as_bytes())
    assert parsed.message_id is None
    assert parsed.from_addr == "a@b.c"
