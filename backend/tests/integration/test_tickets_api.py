"""Integration-тесты POST/GET тикетов + security NFR-1.2 (требуют Postgres).

Запускается в CI (service container) и локально при `POSTGRES_AVAILABLE=1`.
Принципал инжектится через `app.dependency_overrides` (seam #6 — реальная
JWT/сессионная валидация в #29). Заявки коммитятся в эфемерную тестовую БД;
изоляция между тестами не требуется (данные не конфликтуют, number уникален).
"""

from __future__ import annotations

import asyncio
import datetime
import itertools
import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.tickets.enums import TicketStatus, TicketTeam, TicketType
from api.tickets.history import TicketHistoryRepository, record_changes
from api.tickets.models import Ticket
from api.tickets.repository import TicketFilters, TicketRepository
from api.tickets.requester_context import get_platform_client
from api.tickets.schemas import TicketCreate
from api.tickets.state_machine import ALLOWED_TRANSITIONS

pytestmark = pytest.mark.skipif(
    "CI" not in os.environ and "POSTGRES_AVAILABLE" not in os.environ,
    reason=(
        "POST/GET тикетов требуют живой Postgres. Запускается в CI (service"
        " container) и локально при POSTGRES_AVAILABLE=1."
    ),
)


def _use(principal: Principal) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture(autouse=True)
def _override_db_session() -> Iterator[None]:
    """Переопределить get_session на NullPool-движок.

    Глобальный QueuePool-движок кеширует asyncpg-соединения, привязанные к
    event loop первого TestClient; последующие тесты создают новый loop →
    cross-loop ошибки. NullPool открывает свежее соединение на текущем loop.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_test_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _get_test_session
    yield
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_principal, None)
    asyncio.run(engine.dispose())


def _create(client: TestClient, **extra: object) -> Response:
    payload = {"subject": "Нужна помощь", "type": "PAYMENT", **extra}
    return client.post("/api/v1/support/tickets", json=payload)


def _set_team(ticket_id: str, team_value: str) -> None:
    """Назначить команду заявке напрямую в БД (assign endpoint — #12)."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE tickets SET team = :t WHERE id = :id"),
                    {"t": team_value, "id": uuid.UUID(ticket_id)},
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def _set_case_state(ticket_id: str, case_state: str) -> None:
    """Выставить case_state заявке напрямую в БД (подготовка стартовой стадии, E10-2)."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE tickets SET case_state = :s WHERE id = :id"),
                    {"s": case_state, "id": uuid.UUID(ticket_id)},
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def _set_status(ticket_id: str, status_value: str) -> None:
    """Выставить статус заявке напрямую в БД (подготовка стартового состояния)."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE tickets SET status = :s WHERE id = :id"),
                    {"s": status_value, "id": uuid.UUID(ticket_id)},
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


_STATUS_PAIRS = [(a, b) for a, b in itertools.product(TicketStatus, repeat=2) if a != b]


@pytest.mark.parametrize(("source", "target"), _STATUS_PAIRS)
def test_status_transition_enforced(
    client: TestClient, source: TicketStatus, target: TicketStatus
) -> None:
    """DoD #8: разрешённый переход → 200; запрещённый → 422 (по каждой паре)."""
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]  # owner=operator, статус NEW
    _set_status(ticket_id, source.value)
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": target.value})
    if target in ALLOWED_TRANSITIONS.get(source, frozenset()):
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == target.value
    else:
        assert resp.status_code == 422, resp.text


def test_patch_status_change_records_history(client: TestClient) -> None:
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]  # NEW
    assert (
        client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": "OPEN"}).status_code
        == 200
    )
    actions = [
        row["action"]
        for row in client.get(f"/api/v1/support/tickets/{ticket_id}/history").json()["data"]
    ]
    assert "created" in actions
    assert "status_changed" in actions


def test_patch_priority_records_history(client: TestClient) -> None:
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]
    client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"priority": "high"})
    actions = [
        row["action"]
        for row in client.get(f"/api/v1/support/tickets/{ticket_id}/history").json()["data"]
    ]
    assert "priority_changed" in actions


def test_patch_multiple_fields_applies_and_audits(client: TestClient) -> None:
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.patch(
        f"/api/v1/support/tickets/{ticket_id}",
        json={
            "subject": "Уточнённая тема",
            "type": "MAINTENANCE",
            "team": "legal",
            "tags": ["urgent", "vip"],
            "custom_fields": {"floor": 3},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["subject"] == "Уточнённая тема"
    assert data["type"] == "MAINTENANCE"
    assert data["team"] == "legal"
    assert data["tags"] == ["urgent", "vip"]
    assert data["custom_fields"] == {"floor": 3}
    actions = [
        row["action"]
        for row in client.get(f"/api/v1/support/tickets/{ticket_id}/history").json()["data"]
    ]
    assert {"type_changed", "team_changed", "tags_updated"} <= set(actions)


def test_reopen_increments_counter(client: TestClient) -> None:
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.CLOSED.value)
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": "REOPENED"})
    assert resp.status_code == 200
    assert resp.json()["data"]["reopened_count"] == 1


def test_resolve_sets_resolved_at(client: TestClient) -> None:
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.OPEN.value)
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": "RESOLVED"})
    assert resp.status_code == 200
    assert resp.json()["data"]["resolved_at"] is not None


def test_requester_can_close_own_ticket(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]  # NEW, владелец user
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": "CLOSED"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "CLOSED"


def test_requester_cannot_change_priority(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"priority": "high"})
    assert resp.status_code == 403


def test_requester_cannot_set_non_closed_status(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": "OPEN"})
    assert resp.status_code == 403


def test_operator_cannot_patch_foreign_ticket(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]  # team=None
    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.LEGAL}),
        )
    )
    resp = client.patch(f"/api/v1/support/tickets/{ticket_id}", json={"status": "OPEN"})
    assert resp.status_code == 404


def test_patch_without_auth_returns_401(client: TestClient) -> None:
    resp = client.patch(f"/api/v1/support/tickets/{uuid.uuid4()}", json={"status": "OPEN"})
    assert resp.status_code == 401


# --- TicketMessage (#10) ---


def _post_message(
    client: TestClient, ticket_id: str, body: str, *, is_internal: bool = False, **extra: object
) -> Response:
    payload: dict[str, object] = {"body": body, "is_internal": is_internal, **extra}
    return client.post(f"/api/v1/support/tickets/{ticket_id}/messages", json=payload)


def _operator() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        teams=frozenset({TicketTeam.SUPPORT}),
    )


def test_internal_note_hidden_from_requester(client: TestClient) -> None:
    """🔴 NFR-1.3 (блокирует merge): is_internal=true НЕ виден заявителю."""
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, TicketTeam.SUPPORT.value)

    _use(_operator())
    assert _post_message(client, ticket_id, "INTERNAL NOTE", is_internal=True).status_code == 201
    assert _post_message(client, ticket_id, "public reply", is_internal=False).status_code == 201

    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    messages = client.get(f"/api/v1/support/tickets/{ticket_id}/messages").json()["data"]
    bodies = [m["body"] for m in messages]
    assert "public reply" in bodies
    assert "INTERNAL NOTE" not in bodies
    assert all(m["is_internal"] is False for m in messages)


def test_operator_sees_internal_and_public(client: TestClient) -> None:
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, TicketTeam.SUPPORT.value)

    _use(_operator())
    _post_message(client, ticket_id, "INTERNAL", is_internal=True)
    _post_message(client, ticket_id, "PUBLIC", is_internal=False)
    messages = client.get(f"/api/v1/support/tickets/{ticket_id}/messages").json()["data"]
    assert {"INTERNAL", "PUBLIC"} <= {m["body"] for m in messages}


def test_requester_cannot_post_internal(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    assert _post_message(client, ticket_id, "secret", is_internal=True).status_code == 403


def test_operator_can_post_internal_with_author(client: TestClient) -> None:
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, TicketTeam.SUPPORT.value)
    _use(_operator())
    resp = _post_message(client, ticket_id, "note", is_internal=True)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["is_internal"] is True
    assert data["author_type"] == "operator"


def test_requester_message_author_derived_from_principal(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    resp = _post_message(client, ticket_id, "hello")
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["author_type"] == "requester"
    assert data["author_id"] == str(user)
    assert data["is_internal"] is False


def test_post_message_with_attachments(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    file_id = uuid.uuid4()
    resp = _post_message(client, ticket_id, "see file", attachments=[str(file_id)])
    assert resp.status_code == 201
    assert resp.json()["data"]["attachments"] == [str(file_id)]


def test_post_message_records_history(client: TestClient) -> None:
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, TicketTeam.SUPPORT.value)
    _use(_operator())
    _post_message(client, ticket_id, "note", is_internal=True)
    actions = [
        h["action"]
        for h in client.get(f"/api/v1/support/tickets/{ticket_id}/history").json()["data"]
    ]
    assert "message_added" in actions


def test_messages_not_found_for_non_owner(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    assert client.get(f"/api/v1/support/tickets/{ticket_id}/messages").status_code == 404
    assert _post_message(client, ticket_id, "x").status_code == 404


def test_messages_unauthenticated_returns_401(client: TestClient) -> None:
    assert client.get(f"/api/v1/support/tickets/{uuid.uuid4()}/messages").status_code == 401
    assert _post_message(client, str(uuid.uuid4()), "x").status_code == 401


# --- Actions (#12) ---


def _action(client: TestClient, ticket_id: str, action: str, **body: object) -> Response:
    return client.post(f"/api/v1/support/tickets/{ticket_id}/{action}", json=body)


def _history_actions(client: TestClient, ticket_id: str) -> list[str]:
    return [
        h["action"]
        for h in client.get(f"/api/v1/support/tickets/{ticket_id}/history").json()["data"]
    ]


def test_assign_by_operator(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    assignee = uuid.uuid4()
    resp = _action(client, ticket_id, "assign", assignee_id=str(assignee), team="legal")
    assert resp.status_code == 200
    assert resp.json()["data"]["assignee_id"] == str(assignee)
    assert resp.json()["data"]["team"] == "legal"
    assert "reassigned" in _history_actions(client, ticket_id)


def test_requester_cannot_assign(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    assert _action(client, ticket_id, "assign", assignee_id=str(uuid.uuid4())).status_code == 403


def test_escalate_from_open(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.OPEN.value)
    resp = _action(client, ticket_id, "escalate", reason="need L2", team="legal")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ESCALATED"
    assert resp.json()["data"]["team"] == "legal"
    assert "status_changed" in _history_actions(client, ticket_id)


def test_escalate_from_new_is_conflict(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]  # NEW
    assert _action(client, ticket_id, "escalate").status_code == 409


def test_requester_cannot_escalate(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    assert _action(client, ticket_id, "escalate").status_code == 403


def test_resolve_action_sets_resolved_at(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.OPEN.value)
    resp = _action(client, ticket_id, "resolve", resolution_note="fixed")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "RESOLVED"
    assert resp.json()["data"]["resolved_at"] is not None


def test_close_from_resolved(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.RESOLVED.value)
    resp = _action(client, ticket_id, "close")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "CLOSED"
    assert resp.json()["data"]["closed_at"] is not None


def test_close_sets_rating_cta_marker(client: TestClient) -> None:
    # FR-8.1 (#184): закрытие неоценённой заявки выставляет дедуп-маркер CTA в той же
    # транзакции (in-transaction prepare_rating_cta). Сосуществует со статус-маркером.
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.RESOLVED.value)
    resp = _action(client, ticket_id, "close")
    assert resp.status_code == 200
    # Маркер выставлен в той же транзакции на реальном close-пути и персистится.
    # (Сосуществование с last_status_notified покрыто unit-тестом — здесь actor==requester,
    # статус-уведомление само-спам подавляется.)
    assert resp.json()["data"]["custom_fields"]["notifications"]["rating_cta_sent"] is True


def test_close_from_open_is_conflict(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.OPEN.value)
    assert _action(client, ticket_id, "close").status_code == 409


def test_requester_cannot_close(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.RESOLVED.value)
    assert _action(client, ticket_id, "close").status_code == 403


def test_reopen_by_operator_increments_counter(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.CLOSED.value)
    resp = _action(client, ticket_id, "reopen", reason="not fixed")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "REOPENED"
    assert resp.json()["data"]["reopened_count"] == 1


def test_requester_can_reopen_own_ticket(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.RESOLVED.value)
    resp = _action(client, ticket_id, "reopen")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "REOPENED"


def test_rate_by_requester_on_closed(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, TicketTeam.SUPPORT.value)
    _set_status(ticket_id, TicketStatus.CLOSED.value)
    resp = _action(client, ticket_id, "rate", rating=5, comment="great")
    assert resp.status_code == 200
    assert resp.json()["data"]["rating"] == 5
    # Журнал читает оператор (заявителю /history недоступен — NFR-1.3/§3.7).
    _use(_operator())
    assert "rated" in _history_actions(client, ticket_id)


def test_operator_cannot_rate(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_status(ticket_id, TicketStatus.CLOSED.value)
    assert _action(client, ticket_id, "rate", rating=4).status_code == 403


def test_rate_on_open_is_unprocessable(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]  # NEW
    _set_status(ticket_id, TicketStatus.OPEN.value)
    assert _action(client, ticket_id, "rate", rating=4).status_code == 422


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("assign", {"assignee_id": "00000000-0000-0000-0000-000000000001"}),
        ("escalate", {}),
        ("resolve", {}),
        ("close", {}),
        ("reopen", {}),
        ("rate", {"rating": 4}),
    ],
)
def test_action_not_found_for_non_owner(
    client: TestClient, action: str, body: dict[str, object]
) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    resp = client.post(f"/api/v1/support/tickets/{ticket_id}/{action}", json=body)
    assert resp.status_code == 404


def test_action_unauthenticated_returns_401(client: TestClient) -> None:
    assert _action(client, str(uuid.uuid4()), "close").status_code == 401


# --- List + cursor-пагинация + фильтры (#7) ---


def _list_ids(client: TestClient, query: str = "") -> list[str]:
    return [t["id"] for t in client.get(f"/api/v1/support/tickets{query}").json()["data"]]


def test_filter_by_status(client: TestClient) -> None:
    _use(_operator())
    open_id = _create(client).json()["data"]["id"]
    _set_status(open_id, TicketStatus.OPEN.value)
    new_id = _create(client).json()["data"]["id"]
    ids = _list_ids(client, "?status=OPEN")
    assert open_id in ids
    assert new_id not in ids


def test_filter_by_type(client: TestClient) -> None:
    _use(_operator())
    maint = _create(client, type="MAINTENANCE").json()["data"]["id"]
    payment = _create(client).json()["data"]["id"]
    ids = _list_ids(client, "?type=MAINTENANCE")
    assert maint in ids
    assert payment not in ids


def test_filter_by_priority(client: TestClient) -> None:
    _use(_operator())
    high = _create(client, priority="high").json()["data"]["id"]
    normal = _create(client).json()["data"]["id"]
    ids = _list_ids(client, "?priority=high")
    assert high in ids
    assert normal not in ids


def test_filter_by_channel(client: TestClient) -> None:
    _use(_operator())
    email = _create(client, channel="EMAIL").json()["data"]["id"]
    web = _create(client).json()["data"]["id"]
    ids = _list_ids(client, "?channel=EMAIL")
    assert email in ids
    assert web not in ids


def test_filter_by_team(client: TestClient) -> None:
    _use(_operator())
    with_team = _create(client).json()["data"]["id"]
    _set_team(with_team, TicketTeam.SUPPORT.value)
    without = _create(client).json()["data"]["id"]
    ids = _list_ids(client, "?team=support")
    assert with_team in ids
    assert without not in ids


def test_filter_by_assignee_id(client: TestClient) -> None:
    _use(_operator())
    assignee = uuid.uuid4()
    assigned = _create(client).json()["data"]["id"]
    _action(client, assigned, "assign", assignee_id=str(assignee))
    other = _create(client).json()["data"]["id"]
    ids = _list_ids(client, f"?assignee_id={assignee}")
    assert assigned in ids
    assert other not in ids


def test_filter_by_requester_id(client: TestClient) -> None:
    _use(_operator())  # team SUPPORT
    requester = uuid.uuid4()
    on_behalf = _create(client, requester_id=str(requester)).json()["data"]["id"]
    _set_team(on_behalf, TicketTeam.SUPPORT.value)  # сделать видимой оператору
    own = _create(client).json()["data"]["id"]
    ids = _list_ids(client, f"?requester_id={requester}")
    assert on_behalf in ids
    assert own not in ids


def test_filter_by_premises_id(client: TestClient) -> None:
    _use(_operator())
    premises = uuid.uuid4()
    here = _create(client, premises_id=str(premises)).json()["data"]["id"]
    elsewhere = _create(client).json()["data"]["id"]
    ids = _list_ids(client, f"?premises_id={premises}")
    assert here in ids
    assert elsewhere not in ids


def test_filter_by_tag(client: TestClient) -> None:
    _use(_operator())
    tagged = _create(client, tags=["vip", "x"]).json()["data"]["id"]
    plain = _create(client).json()["data"]["id"]
    ids = _list_ids(client, "?tag=vip")
    assert tagged in ids
    assert plain not in ids


def test_filter_sla_breached_in_e1(client: TestClient) -> None:
    """В E1 resolution_due_at всегда NULL → ни одна заявка не «breached»."""
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    assert ticket_id in _list_ids(client, "?sla_breached=false")
    assert ticket_id not in _list_ids(client, "?sla_breached=true")


def test_summary_sla_breached_is_false(client: TestClient) -> None:
    _use(_operator())
    _create(client)
    data = client.get("/api/v1/support/tickets").json()["data"]
    assert data and all(item["sla_breached"] is False for item in data)


def test_sort_by_priority(client: TestClient) -> None:
    _use(_operator())
    low = _create(client, priority="low").json()["data"]["id"]
    crit = _create(client, priority="critical").json()["data"]["id"]
    normal = _create(client, priority="normal").json()["data"]["id"]
    ours = {low, crit, normal}
    desc = [i for i in _list_ids(client, "?sort=-priority") if i in ours]
    assert desc == [crit, normal, low]
    asc = [i for i in _list_ids(client, "?sort=priority") if i in ours]
    assert asc == [low, normal, crit]


def test_sort_by_created_at_is_reversible(client: TestClient) -> None:
    _use(_operator())
    ours = {_create(client).json()["data"]["id"] for _ in range(3)}
    asc = [i for i in _list_ids(client, "?sort=created_at") if i in ours]
    desc = [i for i in _list_ids(client, "?sort=-created_at") if i in ours]
    assert set(asc) == ours
    assert asc == list(reversed(desc))


def test_sort_by_resolution_due_at_accepted(client: TestClient) -> None:
    _use(_operator())
    ours = {_create(client).json()["data"]["id"] for _ in range(2)}
    for key in ("resolution_due_at", "-resolution_due_at"):
        got = {i for i in _list_ids(client, f"?sort={key}") if i in ours}
        assert got == ours


@pytest.mark.parametrize("sort", ["-created_at", "-priority", "resolution_due_at"])
def test_cursor_pagination_consistency(client: TestClient, sort: str) -> None:
    """DoD: страницы покрывают весь набор без пропусков и дублей (по разным sort).

    Покрывает keyset для int (priority) и datetime (created_at/resolution_due_at)
    значений и оба направления (asc/desc).
    """
    _use(_operator())
    created = {_create(client, priority="normal").json()["data"]["id"] for _ in range(5)}
    collected: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # предохранитель от бесконечного цикла
        query = f"?limit=2&sort={sort}"
        if cursor:
            query += f"&cursor={cursor}"
        body = client.get(f"/api/v1/support/tickets{query}").json()
        collected.extend(t["id"] for t in body["data"])
        if not body["pagination"]["has_more"]:
            break
        cursor = body["pagination"]["next_cursor"]
        assert cursor is not None
    ours = [i for i in collected if i in created]
    assert sorted(ours) == sorted(created)  # все элементы
    assert len(ours) == len(set(ours))  # без дублей


def test_list_excludes_other_requesters_tickets(client: TestClient) -> None:
    """🔴 NFR-1.2: список заявителя A не содержит заявок B."""
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    _use(Principal(user_id=user_a, kind=PrincipalKind.REQUESTER))
    a_ticket = _create(client).json()["data"]["id"]
    _use(Principal(user_id=user_b, kind=PrincipalKind.REQUESTER))
    b_ticket = _create(client).json()["data"]["id"]

    _use(Principal(user_id=user_a, kind=PrincipalKind.REQUESTER))
    a_ids = _list_ids(client)
    assert a_ticket in a_ids
    assert b_ticket not in a_ids


def test_invalid_cursor_returns_422(client: TestClient) -> None:
    _use(_operator())
    assert client.get("/api/v1/support/tickets?cursor=not-a-valid-cursor").status_code == 422


def test_list_unauthenticated_returns_401(client: TestClient) -> None:
    assert client.get("/api/v1/support/tickets").status_code == 401


@pytest.mark.asyncio
async def test_list_10k_tickets_under_500ms() -> None:
    """DoD NFR-2.1: пагинированный запрос на 10k заявок < 500 мс."""
    requester = uuid.uuid4()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            rows = [
                {
                    "id": uuid.uuid4(),
                    "number": f"PERF-{requester.hex[:6]}-{i:05d}",
                    "subject": "perf",
                    "description": "",
                    "type": "PAYMENT",
                    "status": "NEW",
                    "priority": "normal",
                    "channel": "WEB_FORM",
                    "access_level": "LOGGED",
                    "requester_id": requester,
                    "reopened_count": 0,
                    "tags": [],
                    "custom_fields": {},
                }
                for i in range(10_000)
            ]
            await session.execute(insert(Ticket), rows)
            await session.commit()

            principal = Principal(user_id=requester, kind=PrincipalKind.REQUESTER)
            start = time.perf_counter()
            result, next_cursor, has_more = await TicketRepository(session).list_tickets(
                principal, filters=TicketFilters(), sort="-created_at", cursor=None, limit=50
            )
            elapsed = time.perf_counter() - start
            assert len(result) == 50
            assert has_more is True
            assert next_cursor is not None
            assert elapsed < 0.5, f"list of 10k took {elapsed:.3f}s (NFR-2.1 < 500ms)"
    finally:
        await engine.dispose()


def test_create_returns_201_with_defaults(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    resp = _create(client)
    assert resp.status_code == 201
    payload = resp.json()
    data = payload["data"]
    assert payload["request_id"]
    assert data["requester_id"] == str(user)
    assert data["status"] == "NEW"
    assert data["access_level"] == "LOGGED"
    assert data["priority"] == "normal"
    assert data["channel"] == "WEB_FORM"
    assert data["number"].startswith("RH-")
    assert data["case_state"] is None


def test_owner_can_get_own_ticket(client: TestClient) -> None:
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == ticket_id


def test_requester_cannot_see_others_ticket(client: TestClient) -> None:
    """NFR-1.2: заявитель B не видит заявку A, даже зная её id → 404."""
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    _use(Principal(user_id=user_a, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]

    _use(Principal(user_id=user_b, kind=PrincipalKind.REQUESTER))
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_requester_id_from_body_ignored_for_requester(client: TestClient) -> None:
    """Заявитель не может подменить requester_id через payload (anti-spoofing)."""
    user_a, victim = uuid.uuid4(), uuid.uuid4()
    _use(Principal(user_id=user_a, kind=PrincipalKind.REQUESTER))
    resp = _create(client, requester_id=str(victim))
    assert resp.status_code == 201
    assert resp.json()["data"]["requester_id"] == str(user_a)


def test_operator_creates_on_behalf_of_requester(client: TestClient) -> None:
    operator, requester = uuid.uuid4(), uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    resp = _create(client, requester_id=str(requester))
    assert resp.status_code == 201
    assert resp.json()["data"]["requester_id"] == str(requester)


def test_request_id_echoed_from_header(client: TestClient) -> None:
    request_id = uuid.uuid4()
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    resp = client.post(
        "/api/v1/support/tickets",
        json={"subject": "x", "type": "PAYMENT"},
        headers={"X-Request-Id": str(request_id)},
    )
    assert resp.status_code == 201
    assert resp.json()["request_id"] == str(request_id)


def test_invalid_request_id_header_falls_back_to_generated(client: TestClient) -> None:
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    resp = client.post(
        "/api/v1/support/tickets",
        json={"subject": "x", "type": "PAYMENT"},
        headers={"X-Request-Id": "not-a-uuid"},
    )
    assert resp.status_code == 201
    # Невалидный заголовок → сгенерированный валидный uuid (парсится без ошибки).
    uuid.UUID(resp.json()["request_id"])


def test_create_writes_created_history_visible_to_operator(client: TestClient) -> None:
    """DoD #9: создание пишет первую строку journal (action=created)."""
    operator = uuid.uuid4()
    _use(
        Principal(
            user_id=operator,
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    ticket_id = _create(client).json()["data"]["id"]  # requester_id == operator (owner)
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/history")
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert any(r["action"] == "created" for r in rows)
    assert rows[0]["actor_id"] == str(operator)


def test_history_forbidden_for_requester(client: TestClient) -> None:
    """Журнал — внутренние данные (§3.7): заявителю-владельцу → 403."""
    user = uuid.uuid4()
    _use(Principal(user_id=user, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/history")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_history_not_found_for_non_owner(client: TestClient) -> None:
    """Чужая заявка → 404 (anti-enumeration) до проверки оператор/нет."""
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _use(Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER))
    resp = client.get(f"/api/v1/support/tickets/{ticket_id}/history")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_record_changes_persists_status_and_reassign() -> None:
    """DoD #9: механизм auto-record пишет status_changed/reassigned (persist)."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            actor = uuid.uuid4()
            ticket = await TicketRepository(session).create(
                TicketCreate(subject="x", type=TicketType.PAYMENT),
                Principal(
                    user_id=actor,
                    kind=PrincipalKind.OPERATOR,
                    teams=frozenset({TicketTeam.SUPPORT}),
                ),
            )
            await session.commit()
            history = TicketHistoryRepository(session)
            await record_changes(
                history,
                ticket.id,
                actor,
                {"status": "NEW", "assignee_id": None},
                {"status": "OPEN", "assignee_id": str(uuid.uuid4())},
            )
            await session.commit()
            rows = await history.list_for_ticket(ticket.id)
            actions = [r.action for r in rows]
            assert "created" in actions
            assert "status_changed" in actions
            assert "reassigned" in actions
            # Порядок DESC по created_at (новые сверху).
            assert rows[0].created_at >= rows[-1].created_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_get_session_dependency_yields_session() -> None:
    """Прямой прогон production-зависимости get_session (в API-тестах переопределена)."""
    async for session in get_session():
        assert isinstance(session, AsyncSession)
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        break


def test_operator_sees_ticket_of_own_team_only(client: TestClient) -> None:
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, TicketTeam.SUPPORT.value)

    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    assert client.get(f"/api/v1/support/tickets/{ticket_id}").status_code == 200

    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.LEGAL}),
        )
    )
    assert client.get(f"/api/v1/support/tickets/{ticket_id}").status_code == 404


# --- from-chat ingest (E3-1, #69) ---

_FROM_CHAT_PATH = "/api/v1/support/tickets/from-chat"


def _service() -> Principal:
    """m2m-принципал (kb-search) для эскалации из чата."""
    return Principal(user_id=uuid.uuid4(), kind=PrincipalKind.SERVICE)


def _from_chat(client: TestClient, **extra: object) -> Response:
    payload: dict[str, object] = {
        "chat_session_id": str(uuid.uuid4()),
        "requester_id": str(uuid.uuid4()),
        **extra,
    }
    return client.post(_FROM_CHAT_PATH, json=payload)


def _ticket_history_actions(ticket_id: str) -> list[str]:
    """Журнал заявки напрямую из БД (endpoint /history требует видимости команды)."""

    async def _inner() -> list[str]:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT action FROM ticket_history WHERE ticket_id = :id"),
                    {"id": uuid.UUID(ticket_id)},
                )
                return [r[0] for r in rows]
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_from_chat_creates_ai_channel_ticket(client: TestClient) -> None:
    _use(_service())
    requester = str(uuid.uuid4())
    resp = _from_chat(
        client,
        requester_id=requester,
        transcript=[{"role": "user", "content": "Не приходит чек"}],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["channel"] == "AI_CHAT"
    assert data["status"] == "NEW"
    # requester_id — из тела (m2m), не из принципала.
    assert data["requester_id"] == requester
    assert data["chat_session_id"] is not None
    # subject выведен из первой реплики пользователя.
    assert data["subject"] == "Не приходит чек"
    # CREATED записан в журнал.
    assert "created" in _ticket_history_actions(data["id"])


def test_from_chat_persists_transcript_in_custom_fields(client: TestClient) -> None:
    _use(_service())
    resp = _from_chat(
        client,
        subject="Тема задана",
        transcript=[
            {"role": "user", "content": "вопрос"},
            {"role": "assistant", "content": "ответ бота"},
        ],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["subject"] == "Тема задана"
    transcript = data["custom_fields"]["chat_transcript"]
    assert [t["role"] for t in transcript] == ["user", "assistant"]


def test_from_chat_dedup_same_session_returns_existing(client: TestClient) -> None:
    _use(_service())
    chat_session = str(uuid.uuid4())
    first = _from_chat(client, chat_session_id=chat_session)
    assert first.status_code == 201, first.text
    second = _from_chat(client, chat_session_id=chat_session)
    assert second.status_code == 201, second.text
    # Повторная эскалация той же сессии — та же заявка, не дубль.
    assert second.json()["data"]["id"] == first.json()["data"]["id"]


def test_from_chat_subject_fallback_without_user_turn(client: TestClient) -> None:
    _use(_service())
    resp = _from_chat(client, transcript=[{"role": "assistant", "content": "только бот"}])
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["subject"] == "Эскалация из AI-чата"


@pytest.mark.parametrize("kind", [PrincipalKind.REQUESTER, PrincipalKind.OPERATOR])
def test_from_chat_forbidden_for_non_service(client: TestClient, kind: PrincipalKind) -> None:
    # anti-spoofing: requester_id берётся из тела → endpoint только для m2m (SERVICE).
    _use(Principal(user_id=uuid.uuid4(), kind=kind, teams=frozenset({TicketTeam.SUPPORT})))
    resp = _from_chat(client, requester_id=str(uuid.uuid4()))
    assert resp.status_code == 403, resp.text


def test_from_chat_unauthenticated_returns_401(client: TestClient) -> None:
    resp = client.post(
        _FROM_CHAT_PATH,
        json={"chat_session_id": str(uuid.uuid4()), "requester_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


def test_from_chat_transcript_over_limit_returns_422(client: TestClient) -> None:
    _use(_service())
    limit = get_settings().chat_transcript_max_turns
    transcript = [{"role": "user", "content": f"m{i}"} for i in range(limit + 1)]
    resp = _from_chat(client, transcript=transcript)
    assert resp.status_code == 422, resp.text


# --- E3-4 (#72): возврат ответа оператора в kb-search (триггер create_message) ---


def _ai_chat_ticket_for_support(client: TestClient) -> str:
    """Создать AI_CHAT-заявку с chat_session_id (from-chat) и отдать её команде
    SUPPORT, чтобы оператор SUPPORT мог отвечать."""
    _use(_service())
    ticket_id = str(_from_chat(client, chat_session_id=str(uuid.uuid4())).json()["data"]["id"])
    _set_team(ticket_id, TicketTeam.SUPPORT.value)
    return ticket_id


def _enable_return_and_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> list[object]:
    """Включить возврат в чат (непустой токен) и подменить фоновую доставку
    рекордером — без реальной сети."""
    import api.tickets.chat_return as chat_return
    import api.tickets.router as router_mod

    captured: list[object] = []

    async def _recorder(reply: object, settings: object) -> None:
        captured.append(reply)

    monkeypatch.setattr(chat_return, "dispatch_operator_reply", _recorder)
    enabled = get_settings().model_copy(update={"kb_search_api_token": "test-m2m"})
    monkeypatch.setattr(router_mod, "get_settings", lambda: enabled)
    return captured


def test_operator_public_reply_schedules_return(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _enable_return_and_capture(monkeypatch)
    ticket_id = _ai_chat_ticket_for_support(client)

    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    resp = _post_message(client, ticket_id, "Здравствуйте, помогаем", is_internal=False)
    assert resp.status_code == 201, resp.text
    assert len(captured) == 1


def test_operator_internal_note_does_not_schedule_return(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # КРИТИЧНО (NFR-1.3): внутренняя заметка НЕ возвращается в чат.
    captured = _enable_return_and_capture(monkeypatch)
    ticket_id = _ai_chat_ticket_for_support(client)

    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    resp = _post_message(client, ticket_id, "внутренняя заметка", is_internal=True)
    assert resp.status_code == 201, resp.text
    assert captured == []


def test_return_disabled_when_token_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.tickets.chat_return as chat_return

    captured: list[object] = []

    async def _recorder(reply: object, settings: object) -> None:
        captured.append(reply)

    monkeypatch.setattr(chat_return, "dispatch_operator_reply", _recorder)
    # get_settings НЕ подменяем → kb_search_api_token пустой (дефолт) → выключено.
    ticket_id = _ai_chat_ticket_for_support(client)
    _use(
        Principal(
            user_id=uuid.uuid4(),
            kind=PrincipalKind.OPERATOR,
            teams=frozenset({TicketTeam.SUPPORT}),
        )
    )
    resp = _post_message(client, ticket_id, "ответ", is_internal=False)
    assert resp.status_code == 201, resp.text
    assert captured == []


# --- Контекст заявителя (enabler #81 для E3-5). FR-2.2, NFR-1.2, AT-003. ---

_RC_PATH = "/api/v1/support/tickets/{}/requester-context"


def _operator_in_team(team: TicketTeam) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, teams=frozenset({team}))


def test_requester_context_gated_returns_degraded(client: TestClient) -> None:
    """Дефолтные настройки (пустой platform_api_token) → 200, degraded=true, секции null."""
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    resp = client.get(_RC_PATH.format(ticket_id))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["degraded"] is True
    assert data["user"] is None
    assert data["premises"] is None
    assert data["booking"] is None
    assert data["collaborator"] is None


def test_requester_context_forbidden_for_requester(client: TestClient) -> None:
    """NFR-1.2: заявитель по СВОЕЙ заявке не видит контекст (операторская функция) → 403."""
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]  # owner = заявитель
    resp = client.get(_RC_PATH.format(ticket_id))
    assert resp.status_code == 403, resp.text


def test_requester_context_not_found_for_stranger(client: TestClient) -> None:
    """Anti-enumeration: посторонний (не владелец / не его команда) → 404, не 403."""
    _use(_operator_in_team(TicketTeam.SUPPORT))
    ticket_id = _create(client).json()["data"]["id"]  # команда не назначена
    # Другой оператор другой команды — заявка ему не видна (storage-level фильтр).
    _use(_operator_in_team(TicketTeam.LEGAL))
    resp = client.get(_RC_PATH.format(ticket_id))
    assert resp.status_code == 404, resp.text


def test_requester_context_populated_from_platform(client: TestClient) -> None:
    """Включённая интеграция (override клиента) → 200 с наполненной секцией user."""
    import datetime

    from api.clients.platform import UserProfile

    class _FakeClient:
        async def get_user(self, user_id: uuid.UUID) -> UserProfile:
            return UserProfile(
                id=user_id,
                display_name="Контекст Тест",
                email="ctx@example.com",
                phone=None,
                role="tenant",
                is_active=True,
                created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            )

        async def get_premises(self, premises_id: uuid.UUID) -> None:
            return None

        async def get_booking(self, booking_id: uuid.UUID) -> None:
            return None

        async def get_collaborator(self, collaborator_id: uuid.UUID) -> None:
            return None

    _use(_operator())
    # Без requester_id оператор сам становится заявителем → заявка ему видна
    # (visibility_filter: requester_id == user_id). get_user зовётся с этим requester_id.
    created = _create(client).json()["data"]
    ticket_id, requester_id = created["id"], created["requester_id"]
    app.dependency_overrides[get_platform_client] = lambda: _FakeClient()
    try:
        resp = client.get(_RC_PATH.format(ticket_id))
    finally:
        app.dependency_overrides.pop(get_platform_client, None)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["degraded"] is False
    assert data["user"] is not None
    assert data["user"]["id"] == requester_id
    assert data["user"]["display_name"] == "Контекст Тест"


# --- case_state переходы + «4 глаза» (E10-2/E10-4 #192/#194) ---


def test_case_state_transition_records_history(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "CLAIM_SUBMITTED")
    resp = _action(client, ticket_id, "case-state", case_state="DOCS_PENDING", note="нужны фото")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["case_state"] == "DOCS_PENDING"
    assert "case_state_changed" in _history_actions(client, ticket_id)


def test_case_state_forbidden_transition_422(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "CLAIM_SUBMITTED")
    # CLAIM_SUBMITTED → PAID запрещён машиной.
    assert _action(client, ticket_id, "case-state", case_state="PAID").status_code == 422


def test_case_state_none_is_422(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]  # не претензионная, case_state=None
    assert _action(client, ticket_id, "case-state", case_state="DOCS_PENDING").status_code == 422


def test_case_state_requester_forbidden_403(client: TestClient) -> None:
    # Заявитель видит СВОЮ заявку (проходит visibility) → упирается в operator-гейт (403).
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "CLAIM_SUBMITTED")
    assert _action(client, ticket_id, "case-state", case_state="DOCS_PENDING").status_code == 403


def test_case_state_unknown_ticket_404(client: TestClient) -> None:
    _use(_operator())
    resp = _action(client, str(uuid.uuid4()), "case-state", case_state="DOCS_PENDING")
    assert resp.status_code == 404


def test_payout_four_eyes_requires_two_distinct_operators(client: TestClient) -> None:
    op_a = _operator()
    op_b = _operator()  # другой user_id
    _use(op_a)
    ticket_id = _create(client).json()["data"]["id"]
    _set_team(ticket_id, "support")  # обе операторы в команде SUPPORT → оба видят заявку
    _set_case_state(ticket_id, "PAYOUT_PENDING")

    # Первый аппрув (op_a): case_state остаётся PAYOUT_PENDING, фиксируется первый подтверждающий.
    r1 = _action(client, ticket_id, "case-state", case_state="PAID")
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["case_state"] == "PAYOUT_PENDING"
    assert "payout_approval_recorded" in _history_actions(client, ticket_id)

    # Тот же оператор повторно → 409 (нужен ДРУГОЙ сотрудник).
    assert _action(client, ticket_id, "case-state", case_state="PAID").status_code == 409

    # Второй, ДРУГОЙ оператор → переход в PAID.
    _use(op_b)
    r2 = _action(client, ticket_id, "case-state", case_state="PAID")
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["case_state"] == "PAID"


def test_case_state_noop_no_history_growth(client: TestClient) -> None:
    _use(_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    before = len(_history_actions(client, ticket_id))
    resp = _action(client, ticket_id, "case-state", case_state="UNDER_REVIEW")  # no-op
    assert resp.status_code == 200
    assert len(_history_actions(client, ticket_id)) == before  # журнал не вырос


# --- POST /decision (E10-3 #193) ---


def _claims_operator() -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.OPERATOR,
        teams=frozenset({TicketTeam.LEGAL}),
    )


def _decide(client: TestClient, ticket_id: str, **body: object) -> Response:
    return client.post(f"/api/v1/support/tickets/{ticket_id}/decision", json=body)


def test_decision_full_sets_fields_and_case_state(client: TestClient) -> None:
    _use(_claims_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    resp = _decide(client, ticket_id, decision="FULL", approved_amount=15000.50)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["decision"] == "FULL"
    assert data["approved_amount"] == 15000.5
    assert data["case_state"] == "DECISION_MADE"  # связка (решение Архитектора)
    assert data["decision_notified_at"] is not None
    assert "case_decided" in _history_actions(client, ticket_id)


def test_decision_rejected_sets_case_state_rejected(client: TestClient) -> None:
    _use(_claims_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    resp = _decide(client, ticket_id, decision="REJECTED", reason="недостаточно доказательств")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["case_state"] == "REJECTED"


def test_decision_full_without_amount_422(client: TestClient) -> None:
    _use(_claims_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    assert _decide(client, ticket_id, decision="FULL").status_code == 422


def test_decision_partial_without_reason_422(client: TestClient) -> None:
    _use(_claims_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    assert _decide(client, ticket_id, decision="PARTIAL", approved_amount=100).status_code == 422


def test_decision_from_claim_submitted_forbidden_422(client: TestClient) -> None:
    # Нельзя решать до рассмотрения (case_state CLAIM_SUBMITTED → DECISION_MADE запрещён машиной).
    _use(_claims_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "CLAIM_SUBMITTED")
    assert _decide(client, ticket_id, decision="FULL", approved_amount=100).status_code == 422


def test_decision_repeat_conflict_409(client: TestClient) -> None:
    _use(_claims_operator())
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    assert _decide(client, ticket_id, decision="FULL", approved_amount=100).status_code == 200
    # Повторное решение запрещено (decision уже принят).
    assert _decide(client, ticket_id, decision="REJECTED", reason="x").status_code == 409


def test_decision_non_claims_operator_403(client: TestClient) -> None:
    _use(_operator())  # команда SUPPORT, не legal/finance
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    assert _decide(client, ticket_id, decision="FULL", approved_amount=100).status_code == 403


def test_decision_requester_403(client: TestClient) -> None:
    requester = uuid.uuid4()
    _use(Principal(user_id=requester, kind=PrincipalKind.REQUESTER))
    ticket_id = _create(client).json()["data"]["id"]
    _set_case_state(ticket_id, "UNDER_REVIEW")
    assert _decide(client, ticket_id, decision="FULL", approved_amount=100).status_code == 403


def test_decision_unknown_ticket_404(client: TestClient) -> None:
    _use(_claims_operator())
    assert (
        _decide(client, str(uuid.uuid4()), decision="FULL", approved_amount=100).status_code == 404
    )


# --- Приём claims (E10-5 #195) ---


def _get_case_details(ticket_id: str) -> dict[str, object] | None:
    """Прочитать TicketCaseDetails (case_type+payload) напрямую из БД, либо None."""

    async def _inner() -> dict[str, object] | None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT case_type, payload FROM ticket_case_details "
                            "WHERE ticket_id = :id"
                        ),
                        {"id": uuid.UUID(ticket_id)},
                    )
                ).first()
                return {"case_type": row[0], "payload": row[1]} if row else None
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_claims_intake_initializes_case(client: TestClient) -> None:
    _use(_operator())
    resp = _create(
        client,
        type="COMPENSATION",
        channel="LK_CLAIM",
        custom_fields={"claim_amount": 60000, "incident_date": "2026-01-01", "evidence": ["f1"]},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["case_state"] == "CLAIM_SUBMITTED"
    assert data["claim_amount"] == 60000.0
    details = _get_case_details(data["id"])
    assert details is not None
    assert details["case_type"] == "COMPENSATION"
    payload = details["payload"]
    assert isinstance(payload, dict)
    assert payload.get("independent_appraisal") is True  # >50 000₽ (D10)
    assert payload.get("late_submission") is True  # вне окна 14 дней
    assert payload.get("evidence") == ["f1"]


def test_claims_intake_small_recent_no_flags(client: TestClient) -> None:
    _use(_operator())
    resp = _create(
        client,
        type="COMPENSATION",
        channel="LK_CLAIM",
        custom_fields={"claim_amount": 1000},
    )
    data = resp.json()["data"]
    assert data["case_state"] == "CLAIM_SUBMITTED"
    details = _get_case_details(data["id"])
    assert details is not None
    payload = details["payload"]
    assert isinstance(payload, dict)
    assert "independent_appraisal" not in payload
    assert "late_submission" not in payload


def test_non_claims_ticket_has_no_case(client: TestClient) -> None:
    _use(_operator())
    resp = _create(client, type="PAYMENT")  # не претензионный
    data = resp.json()["data"]
    assert data["case_state"] is None
    assert _get_case_details(data["id"]) is None


# --- SLA claims по Договору (E10-6 #196) ---


def test_claims_ticket_gets_30_calendar_day_review_deadline(client: TestClient) -> None:
    # Срок рассмотрения 30 кал.дн (Договор 5.8.7) → resolution_due_at = created_at + 30 дней.
    _use(_operator())
    data = _create(client, type="COMPENSATION", channel="LK_CLAIM").json()["data"]
    created = datetime.datetime.fromisoformat(data["created_at"])
    review_due = datetime.datetime.fromisoformat(data["resolution_due_at"])
    assert review_due - created == datetime.timedelta(days=30)


def test_payout_pending_sets_payout_due_at(client: TestClient) -> None:
    # Вход в PAYOUT_PENDING выставляет payout_due_at (10 раб.дн, Договор 5.8.8, Q2).
    _use(_operator())
    ticket_id = _create(client, type="COMPENSATION", channel="LK_CLAIM").json()["data"]["id"]
    _set_case_state(ticket_id, "DECISION_MADE")
    resp = _action(client, ticket_id, "case-state", case_state="PAYOUT_PENDING")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["case_state"] == "PAYOUT_PENDING"
    payout_due = datetime.datetime.fromisoformat(data["payout_due_at"])
    assert payout_due.weekday() < 5  # рабочий день (Пн–Пт)


def test_guarantee_paid_records_regress_seam(client: TestClient) -> None:
    # Выплата GUARANTEE (PAID) фиксирует срок регресса 14 кал.дн в payload (фиксация-seam, Q4).
    op_a = _operator()
    op_b = _operator()
    _use(op_a)
    ticket_id = _create(client, type="GUARANTEE", channel="LK_CLAIM").json()["data"]["id"]
    _set_team(ticket_id, "support")  # оба оператора в SUPPORT → видят заявку
    _set_case_state(ticket_id, "PAYOUT_PENDING")
    assert _action(client, ticket_id, "case-state", case_state="PAID").status_code == 200  # 1-й
    _use(op_b)
    r2 = _action(client, ticket_id, "case-state", case_state="PAID")  # 2-й, другой
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["case_state"] == "PAID"
    details = _get_case_details(ticket_id)
    assert details is not None
    payload = details["payload"]
    assert isinstance(payload, dict)
    assert "regress_due_at" in payload  # срок регресса зафиксирован (боевой путь — upstream)


def _delete_case_details(ticket_id: str) -> None:
    """Удалить TicketCaseDetails (для проверки defensive get-or-create регресс-seam)."""

    async def _inner() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM ticket_case_details WHERE ticket_id = :id"),
                    {"id": uuid.UUID(ticket_id)},
                )
        finally:
            await engine.dispose()

    asyncio.run(_inner())


def test_guarantee_regress_seam_creates_case_details_when_missing(client: TestClient) -> None:
    # Defensive-ветка: деталей нет → регресс-seam создаёт их при PAID (get-or-create).
    op_a = _operator()
    op_b = _operator()
    _use(op_a)
    ticket_id = _create(client, type="GUARANTEE", channel="LK_CLAIM").json()["data"]["id"]
    _delete_case_details(ticket_id)  # детали отсутствуют до выплаты
    _set_team(ticket_id, "support")
    _set_case_state(ticket_id, "PAYOUT_PENDING")
    assert _action(client, ticket_id, "case-state", case_state="PAID").status_code == 200
    _use(op_b)
    assert _action(client, ticket_id, "case-state", case_state="PAID").status_code == 200
    details = _get_case_details(ticket_id)
    assert details is not None  # созданы заново
    assert details["case_type"] == "GUARANTEE"
    assert isinstance(details["payload"], dict)
    assert "regress_due_at" in details["payload"]
