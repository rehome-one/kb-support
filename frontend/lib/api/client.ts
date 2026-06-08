import "server-only";

import type { components, operations } from "@/lib/api/schema";
import { apiFetch, type ApiFetchDeps } from "@/lib/api/transport";

/** RFC 7807 problem+json (контракт `components.schemas.Error`). */
export type Problem = components["schemas"]["Error"];

// problem хранится вне instance (WeakMap) — не перечисляется, не сериализуется
// JSON.stringify, не выгружается при дампе ошибки в лог. Доступ — через геттер.
const problems = new WeakMap<ApiError, Problem>();

/**
 * Ошибка вызова API kb-support. `message` собирается ТОЛЬКО из `status`+`title` —
 * `detail` (потенциальные ПДн) сюда не попадает. Полный `problem` доступен через
 * геттер для UI, но не утекает в логи/сериализацию (инвариант ФЗ-152).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;

  constructor(status: number, title: string, problem?: Problem) {
    super(`${status} ${title}`);
    this.name = "ApiError";
    this.status = status;
    this.title = title;
    if (problem) {
      problems.set(this, problem);
    }
  }

  get problem(): Problem | undefined {
    return problems.get(this);
  }
}

// --- Вывод типов из контракта (operations) ---------------------------------

type JsonOf<T> = T extends { content: { "application/json": infer B } } ? B : never;
type OkJson<O extends keyof operations, S extends keyof operations[O]["responses"]> = JsonOf<
  operations[O]["responses"][S]
>;
type BodyJson<O extends keyof operations> = operations[O] extends {
  requestBody?: { content: { "application/json": infer B } };
}
  ? B
  : never;

export type TicketListResponse = OkJson<"listTickets", 200>;
export type TicketResponse = OkJson<"getTicket", 200>;
export type MessageListResponse = OkJson<"listMessages", 200>;
export type TicketHistoryListResponse = OkJson<"getTicketHistory", 200>;
export type RequesterContextResponse = OkJson<"getRequesterContext", 200>;
export type SuggestedArticlesResponse = OkJson<"getSuggestedArticles", 200>;
export type CannedListResponse = OkJson<"listCannedResponses", 200>;
export type CannedRenderResponse = OkJson<"renderCannedResponse", 200>;
export type MessageResponse = OkJson<"createMessage", 201>;
export type SupportStatsResponse = OkJson<"getSupportStats", 200>;
export type ListTicketsQuery = NonNullable<operations["listTickets"]["parameters"]["query"]>;
export type ListMessagesQuery = NonNullable<operations["listMessages"]["parameters"]["query"]>;
export type SupportStatsQuery = NonNullable<operations["getSupportStats"]["parameters"]["query"]>;
export type TicketUpdateInput = BodyJson<"updateTicket">;
export type MessageCreateInput = BodyJson<"createMessage">;
export type AssignInput = BodyJson<"assignTicket">;
export type EscalateInput = BodyJson<"escalateTicket">;
export type ResolveInput = BodyJson<"resolveTicket">;
// closeTicket не принимает тело (см. контракт) — отдельного Input-типа нет.
export type ReopenInput = BodyJson<"reopenTicket">;
export type RateInput = BodyJson<"rateTicket">;
export type CannedRenderInput = BodyJson<"renderCannedResponse">;

// --- Ядро запроса ----------------------------------------------------------

export interface RequestOptions {
  query?: Record<string, unknown>;
  body?: unknown;
  /** Переопределяет генерируемый X-Request-Id (по умолчанию crypto.randomUUID). */
  requestId?: string;
  /** Idempotency-Key (контракт, optional) для безопасного повтора POST. */
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** Инъекция транспорта для тестов. */
  deps?: ApiFetchDeps;
}

function buildQuery(query: Record<string, unknown> | undefined): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

async function toApiError(response: Response): Promise<ApiError> {
  const contentType = response.headers.get("content-type") ?? "";
  let problem: Problem | undefined;
  if (contentType.includes("application/problem+json")) {
    try {
      problem = (await response.json()) as Problem;
    } catch {
      // Тело не распарсилось — деградируем к статусу, не роняя клиент.
      problem = undefined;
    }
  }
  const title = problem?.title ?? response.statusText ?? "Request failed";
  const status = problem?.status ?? response.status;
  return new ApiError(status, title, problem);
}

/**
 * Низкоуровневый типизированный вызов. Escape-hatch для эндпоинтов без хелпера.
 * Генерирует `X-Request-Id` (переопределяется `options.requestId`), сериализует
 * тело, маппит ошибки в `ApiError`.
 */
export async function request<T>(
  path: string,
  method: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers({
    Accept: "application/json",
    "X-Request-Id": options.requestId ?? crypto.randomUUID(),
  });
  if (options.idempotencyKey) {
    headers.set("Idempotency-Key", options.idempotencyKey);
  }

  let body: string | undefined;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  const response = await apiFetch(
    `${path}${buildQuery(options.query)}`,
    { method, headers, body, signal: options.signal },
    options.deps,
  );

  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// --- Хелперы под ядро заявок (list/get/patch/messages/actions) --------------

const TICKETS = "/api/v1/support/tickets";
const ticketPath = (id: string): string => `${TICKETS}/${encodeURIComponent(id)}`;

export function listTickets(
  query?: ListTicketsQuery,
  deps?: ApiFetchDeps,
): Promise<TicketListResponse> {
  return request<TicketListResponse>(TICKETS, "GET", { query, deps });
}

export function getTicket(id: string, deps?: ApiFetchDeps): Promise<TicketResponse> {
  return request<TicketResponse>(ticketPath(id), "GET", { deps });
}

export function updateTicket(
  id: string,
  input: TicketUpdateInput,
  deps?: ApiFetchDeps,
): Promise<TicketResponse> {
  return request<TicketResponse>(ticketPath(id), "PATCH", { body: input, deps });
}

export function listMessages(
  id: string,
  query?: ListMessagesQuery,
  deps?: ApiFetchDeps,
): Promise<MessageListResponse> {
  return request<MessageListResponse>(`${ticketPath(id)}/messages`, "GET", { query, deps });
}

export function getTicketHistory(
  id: string,
  deps?: ApiFetchDeps,
): Promise<TicketHistoryListResponse> {
  return request<TicketHistoryListResponse>(`${ticketPath(id)}/history`, "GET", { deps });
}

export function getRequesterContext(
  id: string,
  deps?: ApiFetchDeps,
): Promise<RequesterContextResponse> {
  return request<RequesterContextResponse>(`${ticketPath(id)}/requester-context`, "GET", { deps });
}

export function getSuggestedArticles(
  id: string,
  deps?: ApiFetchDeps,
): Promise<SuggestedArticlesResponse> {
  return request<SuggestedArticlesResponse>(`${ticketPath(id)}/suggested-articles`, "GET", {
    deps,
  });
}

const STATS = "/api/v1/support/stats";

export function getSupportStats(
  query?: SupportStatsQuery,
  deps?: ApiFetchDeps,
): Promise<SupportStatsResponse> {
  return request<SupportStatsResponse>(STATS, "GET", { query, deps });
}

const CANNED = "/api/v1/support/canned-responses";

export function listCannedResponses(deps?: ApiFetchDeps): Promise<CannedListResponse> {
  return request<CannedListResponse>(CANNED, "GET", { deps });
}

export function renderCannedResponse(
  id: string,
  input: CannedRenderInput,
  deps?: ApiFetchDeps,
): Promise<CannedRenderResponse> {
  return request<CannedRenderResponse>(`${CANNED}/${encodeURIComponent(id)}/render`, "POST", {
    body: input,
    deps,
  });
}

export function createMessage(
  id: string,
  input: MessageCreateInput,
  deps?: ApiFetchDeps,
): Promise<MessageResponse> {
  // Уникальный ключ на отправку — безопасный повтор POST (сервер дедуплицирует реплей).
  return request<MessageResponse>(`${ticketPath(id)}/messages`, "POST", {
    body: input,
    idempotencyKey: crypto.randomUUID(),
    deps,
  });
}

export function assignTicket(
  id: string,
  input: AssignInput,
  deps?: ApiFetchDeps,
): Promise<TicketResponse> {
  return request<TicketResponse>(`${ticketPath(id)}/assign`, "POST", { body: input, deps });
}

export function escalateTicket(
  id: string,
  input: EscalateInput,
  deps?: ApiFetchDeps,
): Promise<TicketResponse> {
  return request<TicketResponse>(`${ticketPath(id)}/escalate`, "POST", { body: input, deps });
}

export function resolveTicket(
  id: string,
  input: ResolveInput,
  deps?: ApiFetchDeps,
): Promise<TicketResponse> {
  return request<TicketResponse>(`${ticketPath(id)}/resolve`, "POST", { body: input, deps });
}

export function closeTicket(id: string, deps?: ApiFetchDeps): Promise<TicketResponse> {
  return request<TicketResponse>(`${ticketPath(id)}/close`, "POST", { deps });
}

export function reopenTicket(
  id: string,
  input: ReopenInput,
  deps?: ApiFetchDeps,
): Promise<TicketResponse> {
  return request<TicketResponse>(`${ticketPath(id)}/reopen`, "POST", { body: input, deps });
}

export function rateTicket(
  id: string,
  input: RateInput,
  deps?: ApiFetchDeps,
): Promise<TicketResponse> {
  return request<TicketResponse>(`${ticketPath(id)}/rate`, "POST", { body: input, deps });
}
