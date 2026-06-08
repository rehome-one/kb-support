"""Unit-тесты гистограммы размера вложений (E7-10, #151) — без сети/БД.

`record_attachment_size` вызывается ТОЛЬКО для успешно загруженных вложений
(accepted-only): не при выключенном kb-files и не при сбое upload.
"""

from __future__ import annotations

import asyncio
import uuid

from prometheus_client import REGISTRY

from api.clients.errors import ExternalServiceError
from api.clients.kb_files.models import StoredFile
from api.email.ingestion import _upload_attachments
from api.email.parser import ParsedAttachment


class _FakeKbFiles:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def upload(self, *, filename: str, content_type: str, content: bytes) -> StoredFile:
        if self.fail:
            raise ExternalServiceError("kb_files", "upload", "boom")
        return StoredFile(
            id=str(uuid.uuid4()), filename=filename, content_type=content_type, size=len(content)
        )


def _att() -> ParsedAttachment:
    return ParsedAttachment(
        filename="doc.pdf", content_type="application/pdf", content=b"PDFB", size=4
    )


def _count() -> float:
    return REGISTRY.get_sample_value("email_attachment_size_bytes_count") or 0.0


def test_records_size_on_successful_upload() -> None:
    before = _count()
    file_ids, deferred = asyncio.run(_upload_attachments((_att(),), _FakeKbFiles()))
    assert file_ids and deferred is None
    assert _count() == before + 1  # размер принятого вложения учтён


def test_no_record_when_kb_files_off() -> None:
    before = _count()
    asyncio.run(_upload_attachments((_att(),), None))
    assert _count() == before  # выключено → не загружено → не учитываем


def test_no_record_on_upload_failure() -> None:
    before = _count()
    file_ids, deferred = asyncio.run(_upload_attachments((_att(),), _FakeKbFiles(fail=True)))
    assert file_ids == []
    assert deferred == {"failed_count": 1}
    assert _count() == before  # сбой загрузки → в гистограмму «принятого» не идёт
