/**
 * Канонические фикстуры для E2E-smoke (#49). Единственный источник правды о
 * данных, которые отдаёт мок-бэкенд: импортируются и сервером-фикстурой
 * (`fixture-server.mjs`), и спекой (`smoke.spec.ts`) — чтобы ассерты и ответы
 * не расходились. ПДн — синтетические (вымышленный заявитель).
 *
 * Формы соответствуют контракту `docs/openapi.yaml` (TicketSummary / Ticket /
 * TicketMessage / TicketHistory + конверт ResponseEnvelope с `data`).
 */

export const TICKET_ID = "11111111-1111-4111-8111-111111111111";
export const TICKET_NUMBER = "RH-2026-00042";
export const TICKET_SUBJECT = "Не работает лифт в подъезде";
export const REQUESTER_ID = "22222222-2222-4222-8222-222222222222";
export const OPERATOR_ID = "33333333-3333-4333-8333-333333333333";

/** Краткая карточка для списка (`GET /tickets` → data[]). */
export const TICKET_SUMMARY = {
  id: TICKET_ID,
  number: TICKET_NUMBER,
  subject: TICKET_SUBJECT,
  status: "NEW",
  priority: "high",
  type: "MAINTENANCE",
  channel: "AI_CHAT",
  requester_id: REQUESTER_ID,
  assignee_id: null,
  team: "support",
  first_response_due_at: null,
  resolution_due_at: "2026-06-02T12:00:00Z",
  sla_breached: false,
  tags: ["лифт"],
  created_at: "2026-06-01T09:00:00Z",
  updated_at: "2026-06-01T09:00:00Z",
};

/** Полная заявка (`GET /tickets/{id}` → data). */
export const TICKET = {
  ...TICKET_SUMMARY,
  allowed_status_transitions: ["OPEN", "PENDING", "CLOSED"],
  description: "Лифт стоит со вчерашнего вечера, жильцы поднимаются пешком.",
  premises_id: null,
  booking_id: null,
  reopened_count: 0,
  access_level: "LOGGED",
};

/** Исходная переписка (`GET /tickets/{id}/messages` → data[], хронологически). */
export const INITIAL_MESSAGES = [
  {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ticket_id: TICKET_ID,
    author_id: REQUESTER_ID,
    author_type: "requester",
    body: "Здравствуйте! Когда починят лифт?",
    is_internal: false,
    created_at: "2026-06-01T09:01:00Z",
  },
];

/** Журнал действий (`GET /tickets/{id}/history` → data[], обратно-хронологически). */
export const HISTORY = [
  {
    id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ticket_id: TICKET_ID,
    actor_id: REQUESTER_ID,
    action: "created",
    from_value: null,
    to_value: { status: "NEW" },
    created_at: "2026-06-01T09:00:00Z",
  },
];
