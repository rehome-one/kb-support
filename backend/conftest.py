"""Pytest fixtures для kb-support backend.

На bootstrap'е — один TestClient fixture. Расширится по мере появления
зависимостей (DB session, Redis, external API mocks).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Sync FastAPI TestClient (starlette httpx wrapper)."""
    with TestClient(app) as c:
        yield c
