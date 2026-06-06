"""HTTP-клиент kb-files (E7-1, #143) — загрузка вложений заявок в MinIO по API.

Поверх resilient-фундамента #70 (AT-003), провизорный контракт (ADR-0010 Решение 4,
стиль ADR-0006). Config-gated по пустому `kb_files_api_token` (инертно до #77,
фабрика — у потребителя #145). Связь — только по HTTP (арх-константа): НЕ shared
bucket MinIO, без прямого доступа к чужому хранилищу.
"""

from api.clients.kb_files.adapter import HttpKbFilesClient
from api.clients.kb_files.models import StoredFile
from api.clients.kb_files.protocol import KbFilesClient

__all__ = ["HttpKbFilesClient", "KbFilesClient", "StoredFile"]
