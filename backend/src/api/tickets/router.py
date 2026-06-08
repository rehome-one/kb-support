"""Эндпоинты ядра заявок: создание (POST) и карточка (GET) — E1, #6.

Контракт: `POST /api/v1/support/tickets` (201), `GET /api/v1/support/tickets/{id}`
(200 / 404). Аутентификация — `get_current_principal` (seam, #29). Доступ к
карточке — storage-level фильтр (NFR-1.2): чужая/несуществующая заявка → 404.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.canned.usage import record_canned_usage
from api.clients.kb_files import KbFilesClient
from api.clients.kb_files.deps import get_kb_files_client
from api.clients.kb_search import KbSearchClient
from api.clients.kb_search.deps import get_kb_search_client
from api.clients.platform import PlatformClient
from api.config import get_settings
from api.db import get_session
from api.email.ingestion import ingest_email
from api.email.parser import parse_email
from api.errors import ProblemException
from api.notifications.dispatcher import (
    notify_low_rating,
    notify_message,
    prepare_rating_cta,
    prepare_status_notification,
    schedule_rating_cta,
    schedule_status_notification,
)
from api.tickets.actions import TicketActionService
from api.tickets.enums import (
    TicketChannel,
    TicketPriority,
    TicketStatus,
    TicketTeam,
    TicketType,
)
from api.tickets.history import TicketHistoryAction, TicketHistoryRepository
from api.tickets.messages import (
    TicketMessageRepository,
    is_public_operator_reply,
    message_added_payload,
)
from api.tickets.models import Ticket
from api.tickets.pagination import TicketSortKey
from api.tickets.repository import TicketFilters, TicketRepository
from api.tickets.requester_context import (
    RequesterContext,
    assemble_requester_context,
    get_platform_client,
)
from api.tickets.schemas import (
    AssignInput,
    EmailIngest,
    EscalateInput,
    Pagination,
    RateInput,
    ReopenInput,
    RequesterBookingRead,
    RequesterCollaboratorRead,
    RequesterContextEnvelope,
    RequesterContextRead,
    RequesterPremisesRead,
    RequesterUserRead,
    ResolveInput,
    TicketCreate,
    TicketEnvelope,
    TicketFromChat,
    TicketHistoryListEnvelope,
    TicketHistoryRead,
    TicketListEnvelope,
    TicketMessageCreate,
    TicketMessageEnvelope,
    TicketMessageListEnvelope,
    TicketMessageRead,
    TicketRead,
    TicketSummaryRead,
    TicketUpdate,
    WebFormTicketCreate,
)
from api.tickets.sla_metrics import record_first_response
from api.tickets.state_machine import is_allowed_transition
from api.tickets.suggested_articles import (
    SuggestedArticlesEnvelope,
    suggest_for_ticket,
)

router = APIRouter(prefix="/api/v1/support/tickets", tags=["Tickets"])

# Заявитель может менять только статус (и только в CLOSED — «закрыть свой»).
_REQUESTER_ALLOWED_FIELDS = frozenset({"status"})


def _authorize_update(principal: Principal, payload: TicketUpdate) -> None:
    """RBAC PATCH: оператор — любые поля; заявитель — только status→CLOSED (иначе 403)."""
    if principal.is_operator:
        return
    changed_only_status = payload.model_fields_set <= _REQUESTER_ALLOWED_FIELDS
    if not changed_only_status or payload.status is not TicketStatus.CLOSED:
        raise ProblemException.forbidden(detail="Requesters may only close their own ticket")


def _require_operator(principal: Principal) -> None:
    """RBAC action-эндпоинтов, доступных только операторам."""
    if not principal.is_operator:
        raise ProblemException.forbidden(detail="Operator role required")


def _ticket_envelope(ticket: Ticket, x_request_id: str | None) -> TicketEnvelope:
    return TicketEnvelope(
        data=TicketRead.model_validate(ticket),
        request_id=_resolve_request_id(x_request_id),
    )


def _requester_context_read(context: RequesterContext) -> RequesterContextRead:
    """Смаппить доменные DTO platform-клиента в схему ответа kb-support (#81).

    Провизорная форма rehome.one наружу не отдаётся — только наши схемы (`model_validate`
    по `from_attributes`). `None`-секция остаётся `None` (сущности нет/сосед недоступен)."""
    return RequesterContextRead(
        user=RequesterUserRead.model_validate(context.user) if context.user else None,
        premises=(
            RequesterPremisesRead.model_validate(context.premises) if context.premises else None
        ),
        booking=RequesterBookingRead.model_validate(context.booking) if context.booking else None,
        collaborator=(
            RequesterCollaboratorRead.model_validate(context.collaborator)
            if context.collaborator
            else None
        ),
        degraded=context.degraded,
    )


def _resolve_request_id(raw: str | None) -> uuid.UUID:
    """Взять request_id из заголовка `X-Request-Id` или сгенерировать новый."""
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return uuid.uuid4()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketEnvelope,
    summary="Создать заявку",
)
async def create_ticket(
    payload: TicketCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).create(payload, principal)
    await session.commit()
    await session.refresh(ticket)
    return TicketEnvelope(
        data=TicketRead.model_validate(ticket),
        request_id=_resolve_request_id(x_request_id),
    )


@router.post(
    "/from-chat",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketEnvelope,
    summary="Создать заявку из эскалации AI-чата",
)
async def create_ticket_from_chat(
    payload: TicketFromChat,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    # m2m-only (kb-search). requester_id берётся из тела, поэтому endpoint обязан
    # быть закрыт для не-SERVICE принципалов — иначе заявитель создаст заявку от
    # чужого имени (anti-spoofing, #69). Заголовок Idempotency-Key контракта
    # информативен: идемпотентность обеспечивается дедупом по chat_session_id.
    if principal.kind is not PrincipalKind.SERVICE:
        raise ProblemException.forbidden(detail="Chat escalation is a service-to-service operation")
    max_turns = get_settings().chat_transcript_max_turns
    if payload.transcript is not None and len(payload.transcript) > max_turns:
        raise ProblemException.unprocessable(detail=f"transcript exceeds {max_turns} turns")
    ticket, _created = await TicketRepository(session).create_from_chat(payload, principal)
    await session.commit()
    await session.refresh(ticket)
    return _ticket_envelope(ticket, x_request_id)


# Фиксированный body начального сообщения-носителя вложений веб-формы (решение
# Архитектора #148: description НЕ дублируется — живёт только на Ticket.description).
_WEB_FORM_ATTACHMENT_NOTE = "Вложения, приложенные при создании обращения через веб-форму"


@router.post(
    "/from-web-form",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketEnvelope,
    summary="Создать заявку через веб-форму ЛК",
)
async def create_ticket_from_web_form(
    payload: WebFormTicketCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    # Self-service заявителя из ЛК (FR-1.3, ADR-0010 Решение 2). Только kind=REQUESTER:
    # оператор создаёт через generic POST /tickets (от имени заявителя). requester_id и
    # channel форсятся сервером (схема их не несёт) — anti-spoofing.
    if principal.kind is not PrincipalKind.REQUESTER:
        raise ProblemException.forbidden(
            detail="Web form submission is a requester self-service action"
        )
    create = TicketCreate(
        subject=payload.subject,
        type=payload.type,
        description=payload.description,
        priority=payload.priority,
        channel=TicketChannel.WEB_FORM,
        requester_id=None,
        premises_id=payload.premises_id,
        booking_id=payload.booking_id,
        tags=payload.tags,
    )
    repo = TicketRepository(session)
    ticket = await repo.create(create, principal)
    # Вложения живут на TicketMessage (у Ticket нет колонки attachments). Маркерное
    # начальное сообщение создаётся ТОЛЬКО при непустых attachments (решение Архитектора).
    if payload.attachments:
        await TicketMessageRepository(session).create(
            ticket.id,
            principal,
            body=_WEB_FORM_ATTACHMENT_NOTE,
            is_internal=False,
            attachments=payload.attachments,
        )
    await session.commit()
    await session.refresh(ticket)
    return _ticket_envelope(ticket, x_request_id)


@router.post(
    "/from-email",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketEnvelope,
    summary="Принять входящее письмо (email-шлюз)",
)
async def create_ticket_from_email(
    payload: EmailIngest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    platform_client: PlatformClient | None = Depends(get_platform_client),
    kb_files_client: KbFilesClient | None = Depends(get_kb_files_client),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    # m2m-only (email-шлюз). Отправитель резолвится сервером из письма (anti-spoofing,
    # ADR-0010 Решение 3) — endpoint обязан быть закрыт для не-SERVICE принципалов,
    # иначе заявитель «пришлёт письмо» от чужого имени. Контур тонкий: декод → парсер
    # #144 → ingest_email (вся логика дедупа/резолва/вложений — ядро PR-A).
    if principal.kind is not PrincipalKind.SERVICE:
        raise ProblemException.forbidden(detail="Email ingestion is a service-to-service operation")
    settings = get_settings()
    # Битый base64 — транспортная ошибка (до парсинга) → 400. raw_message в ошибку/лог
    # НЕ попадает (ФЗ-152). Декод строгий (validate=True): мусор не «доедается» молча.
    try:
        raw = base64.b64decode(payload.raw_message, validate=True)
    except (binascii.Error, ValueError):
        raise ProblemException.bad_request(detail="raw_message is not valid base64") from None
    # Anti-DoS: цельное письмо целиком декодируется в память до парсинга → лимит на
    # размер тела (отдельно от лимита вложений). Превышение → 422 (решение Архитектора).
    if len(raw) > settings.email_raw_max_bytes:
        raise ProblemException.unprocessable(detail="email message exceeds size limit")
    # Malformed RFC822 НЕ ошибка контура: парсер #144 malformed-safe (parse_error в
    # ParsedEmail) → письмо принимается, email_parse_error в custom_fields (оператор видит).
    parsed = parse_email(raw, max_attachment_bytes=settings.email_attachment_max_bytes)
    result = await ingest_email(
        session, parsed, platform_client=platform_client, kb_files_client=kb_files_client
    )
    # ingest_email только flush'ит (commit за вызывающим); recovery-ветка внутри сама
    # делает rollback и перечитывает заявку через session.get → result.ticket валиден
    # после commit/refresh. created/deduped в контракт не выносим — 201 + ссылка.
    await session.commit()
    await session.refresh(result.ticket)
    return _ticket_envelope(result.ticket, x_request_id)


@router.get("", response_model=TicketListEnvelope, summary="Список заявок")
async def list_tickets(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
    type_filter: TicketType | None = Query(default=None, alias="type"),
    priority: TicketPriority | None = Query(default=None),
    channel: TicketChannel | None = Query(default=None),
    team: TicketTeam | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None),
    requester_id: uuid.UUID | None = Query(default=None),
    premises_id: uuid.UUID | None = Query(default=None),
    tag: str | None = Query(default=None),
    sla_breached: bool | None = Query(default=None),
    sort: TicketSortKey | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketListEnvelope:
    filters = TicketFilters(
        status=status_filter.value if status_filter else None,
        type=type_filter.value if type_filter else None,
        priority=priority.value if priority else None,
        channel=channel.value if channel else None,
        team=team.value if team else None,
        assignee_id=assignee_id,
        requester_id=requester_id,
        premises_id=premises_id,
        tag=tag,
        sla_breached=sla_breached,
    )
    try:
        rows, next_cursor, has_more = await TicketRepository(session).list_tickets(
            principal, filters=filters, sort=sort, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise ProblemException.unprocessable(detail="Invalid pagination cursor") from exc
    return TicketListEnvelope(
        data=[TicketSummaryRead.model_validate(ticket) for ticket in rows],
        pagination=Pagination(next_cursor=next_cursor, has_more=has_more),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/{ticket_id}",
    response_model=TicketEnvelope,
    summary="Карточка заявки",
)
async def get_ticket(
    ticket_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    return TicketEnvelope(
        data=TicketRead.model_validate(ticket),
        request_id=_resolve_request_id(x_request_id),
    )


@router.patch(
    "/{ticket_id}",
    response_model=TicketEnvelope,
    summary="Обновить заявку",
)
async def update_ticket(
    ticket_id: uuid.UUID,
    payload: TicketUpdate,
    background: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    repo = TicketRepository(session)
    ticket = await repo.get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    _authorize_update(principal, payload)
    # Валидация перехода статуса (запрещённый → 422, см. план/#11 про 409).
    if (
        payload.status is not None
        and payload.status.value != ticket.status
        and not is_allowed_transition(TicketStatus(ticket.status), payload.status)
    ):
        raise ProblemException.unprocessable(
            detail=f"Status transition {ticket.status} → {payload.status.value} is not allowed"
        )
    old_status = ticket.status  # до apply_update (он перетирает ticket.status)
    updated = await repo.apply_update(ticket, payload, principal)
    # E7-8 (#149): решение об уведомлении + дедуп-маркер пишутся В ЭТОЙ транзакции.
    notice = prepare_status_notification(updated, old_status, principal.user_id)
    cta = prepare_rating_cta(updated, old_status)  # FR-8.1: CTA на CLOSED через PATCH (#184)
    await session.commit()
    await session.refresh(updated)
    if notice is not None:  # планируем веер каналов после commit (fire-after)
        schedule_status_notification(background, updated, notice, get_settings())
    if cta:
        schedule_rating_cta(background, updated, get_settings())
    return TicketEnvelope(
        data=TicketRead.model_validate(updated),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/{ticket_id}/history",
    response_model=TicketHistoryListEnvelope,
    summary="Журнал действий по заявке (внутренний)",
)
async def get_ticket_history(
    ticket_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketHistoryListEnvelope:
    # Сначала видимость самой заявки (404 для чужой/несуществующей —
    # anti-enumeration), затем — журнал только операторам (внутренние данные §3.7).
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    if not principal.is_operator:
        raise ProblemException.forbidden(detail="Ticket history is available to operators only")
    rows = await TicketHistoryRepository(session).list_for_ticket(ticket_id)
    return TicketHistoryListEnvelope(
        data=[TicketHistoryRead.model_validate(row) for row in rows],
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/{ticket_id}/requester-context",
    response_model=RequesterContextEnvelope,
    summary="Контекст заявителя (профиль/квартира/бронь)",
)
async def get_requester_context(
    ticket_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    platform: PlatformClient | None = Depends(get_platform_client),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> RequesterContextEnvelope:
    # Доступ как у /history: сначала видимость заявки (404 для чужой/несуществующей —
    # anti-enumeration), затем — только операторам (контекст заявителя это операторская
    # функция FR-2.2; заявителю по своей же заявке тоже 403, чтобы ПДн не утекли).
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    if not principal.is_operator:
        raise ProblemException.forbidden(detail="Requester context is available to operators only")
    context = await assemble_requester_context(ticket, platform)
    return RequesterContextEnvelope(
        data=_requester_context_read(context),
        request_id=_resolve_request_id(x_request_id),
    )


@router.get(
    "/{ticket_id}/suggested-articles",
    response_model=SuggestedArticlesEnvelope,
    summary="Предложенные статьи базы знаний по заявке",
)
async def get_suggested_articles(
    ticket_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    kb_search: KbSearchClient | None = Depends(get_kb_search_client),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> SuggestedArticlesEnvelope:
    # Доступ как у requester-context: видимость заявки (404 anti-enum), затем operator-only
    # (FR-5.4 — операторская функция). kb-search config-gated: выключено/недоступно →
    # degraded=true, пустой список (не 5xx).
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    if not principal.is_operator:
        raise ProblemException.forbidden(
            detail="Suggested articles are available to operators only"
        )
    result = await suggest_for_ticket(ticket, kb_search)
    return SuggestedArticlesEnvelope(data=result, request_id=_resolve_request_id(x_request_id))


@router.get(
    "/{ticket_id}/messages",
    response_model=TicketMessageListEnvelope,
    summary="Переписка по заявке",
)
async def list_messages(
    ticket_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketMessageListEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    # NFR-1.3: внутренние заметки исключаются для заявителя на уровне SQL.
    messages = await TicketMessageRepository(session).list_for_principal(ticket_id, principal)
    return TicketMessageListEnvelope(
        data=[TicketMessageRead.model_validate(message) for message in messages],
        request_id=_resolve_request_id(x_request_id),
    )


@router.post(
    "/{ticket_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketMessageEnvelope,
    summary="Добавить сообщение или внутреннюю заметку",
)
async def create_message(
    ticket_id: uuid.UUID,
    payload: TicketMessageCreate,
    background: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketMessageEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    # NFR-1.3: внутреннюю заметку может оставить только оператор.
    if payload.is_internal and not principal.is_operator:
        raise ProblemException.forbidden(detail="Only operators may post internal notes")
    message = await TicketMessageRepository(session).create(
        ticket_id,
        principal,
        body=payload.body,
        is_internal=payload.is_internal,
        attachments=payload.attachments,
    )
    # SLA-факт (E4-5 #89): первый ПУБЛИЧНЫЙ ответ оператора фиксирует first_responded_at
    # (идемпотентно — только если ещё не задан). Внутренняя заметка ответом не считается
    # (NFR-1.3). На норматив решения это не влияет — отдельный дедлайн.
    if is_public_operator_reply(message) and ticket.first_responded_at is None:
        ticket.first_responded_at = datetime.datetime.now(datetime.UTC)
        record_first_response(ticket)  # TTFR + first-response breach (E4-7 #91)
    await TicketHistoryRepository(session).record(
        ticket_id,
        principal.user_id,
        TicketHistoryAction.MESSAGE_ADDED,
        to_value=message_added_payload(message),
    )
    # E6-4 (#128): ответ из шаблона учитывается в usage_count (best-effort, SAVEPOINT —
    # сбой/несуществующий шаблон не валит отправку; ADR-0009 Решение 5).
    if payload.canned_response_id is not None:
        await record_canned_usage(session, payload.canned_response_id)
    await session.commit()
    await session.refresh(message)
    # E3-4 (#72): публичный ответ оператора по AI_CHAT-заявке возвращается в
    # chat-session фоном (NFR-1.3 gate + плоский DTO извлекается здесь, пока жива
    # сессия; внутренние заметки НЕ уходят). Выключено без kb_search_api_token.
    # E7-8 (#149): единая точка веера уведомлений о новом ответе по каналам (chat #72 +
    # email #147 + будущие push/SMS #150). NFR-1.3/config-gate наследуются каналами.
    notify_message(background, ticket, message, get_settings())
    return TicketMessageEnvelope(
        data=TicketMessageRead.model_validate(message),
        request_id=_resolve_request_id(x_request_id),
    )


# --- Action-эндпоинты (#12): переход статуса/поле + история + RBAC ---


@router.post("/{ticket_id}/assign", response_model=TicketEnvelope, summary="Назначить заявку")
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: AssignInput,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    _require_operator(principal)
    await TicketActionService(session).assign(
        ticket, principal.user_id, assignee_id=payload.assignee_id, team=payload.team
    )
    await session.commit()
    await session.refresh(ticket)
    return _ticket_envelope(ticket, x_request_id)


@router.post("/{ticket_id}/escalate", response_model=TicketEnvelope, summary="Эскалировать")
async def escalate_ticket(
    ticket_id: uuid.UUID,
    payload: EscalateInput,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    _require_operator(principal)
    await TicketActionService(session).escalate(
        ticket, principal.user_id, team=payload.team, reason=payload.reason
    )
    await session.commit()
    await session.refresh(ticket)
    return _ticket_envelope(ticket, x_request_id)


@router.post("/{ticket_id}/resolve", response_model=TicketEnvelope, summary="Отметить решённой")
async def resolve_ticket(
    ticket_id: uuid.UUID,
    payload: ResolveInput,
    background: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    _require_operator(principal)
    old_status = ticket.status
    await TicketActionService(session).resolve(
        ticket, principal.user_id, resolution_note=payload.resolution_note
    )
    notice = prepare_status_notification(ticket, old_status, principal.user_id)
    await session.commit()
    await session.refresh(ticket)
    if notice is not None:
        schedule_status_notification(background, ticket, notice, get_settings())
    return _ticket_envelope(ticket, x_request_id)


@router.post("/{ticket_id}/close", response_model=TicketEnvelope, summary="Закрыть заявку")
async def close_ticket(
    ticket_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    _require_operator(principal)
    old_status = ticket.status
    await TicketActionService(session).close(ticket, principal.user_id)
    notice = prepare_status_notification(ticket, old_status, principal.user_id)
    cta = prepare_rating_cta(ticket, old_status)  # FR-8.1: CTA «оцени заявку» (#184)
    await session.commit()
    await session.refresh(ticket)
    if notice is not None:
        schedule_status_notification(background, ticket, notice, get_settings())
    if cta:
        schedule_rating_cta(background, ticket, get_settings())
    return _ticket_envelope(ticket, x_request_id)


@router.post("/{ticket_id}/reopen", response_model=TicketEnvelope, summary="Переоткрыть заявку")
async def reopen_ticket(
    ticket_id: uuid.UUID,
    payload: ReopenInput,
    background: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    # Переоткрыть может оператор или заявитель-владелец (видимость → 404).
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    old_status = ticket.status
    await TicketActionService(session).reopen(ticket, principal.user_id, reason=payload.reason)
    # REOPENED не в NOTIFIED_STATUSES → prepare сбросит дедуп-маркер (M2), уведомления нет.
    notice = prepare_status_notification(ticket, old_status, principal.user_id)
    await session.commit()
    await session.refresh(ticket)
    if notice is not None:
        schedule_status_notification(background, ticket, notice, get_settings())
    return _ticket_envelope(ticket, x_request_id)


@router.post("/{ticket_id}/rate", response_model=TicketEnvelope, summary="Оценка заявителя")
async def rate_ticket(
    ticket_id: uuid.UUID,
    payload: RateInput,
    background: BackgroundTasks,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> TicketEnvelope:
    ticket = await TicketRepository(session).get_for_principal(ticket_id, principal)
    if ticket is None:
        raise ProblemException.not_found(detail="Ticket not found")
    # Оценку ставит только заявитель (не оператор).
    if principal.kind is not PrincipalKind.REQUESTER:
        raise ProblemException.forbidden(detail="Only the requester may rate a ticket")
    await TicketActionService(session).rate(
        ticket, principal.user_id, rating=payload.rating, comment=payload.comment
    )
    await session.commit()
    await session.refresh(ticket)
    # FR-8.2: низкую оценку (1-2) — супервайзеру fire-after (config-gated seam, #183).
    notify_low_rating(background, ticket, get_settings())
    return _ticket_envelope(ticket, x_request_id)
