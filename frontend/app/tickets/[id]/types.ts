import type {
  MessageListResponse,
  TicketHistoryListResponse,
  TicketResponse,
} from "@/lib/api/client";

// Доменные типы карточки выведены из контракта (только типовой импорт — server-only
// runtime клиента в клиентский бандл не тянется).
export type Ticket = NonNullable<TicketResponse["data"]>;
export type TicketMessage = NonNullable<MessageListResponse["data"]>[number];
export type TicketHistoryEntry = NonNullable<TicketHistoryListResponse["data"]>[number];

/**
 * Результат мутирующего действия через server action. Ошибка пересекает границу
 * сервер→клиент только как `{status,title}` — `detail`/problem (потенц. ПДн) остаются
 * на сервере (ФЗ-152). 422 (недопустимый переход/валидация) и 409 (конфликт) — сюда же.
 */
export type ActionResult = { ok: true } | { ok: false; status: number; title: string };
