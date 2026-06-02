import type {
  MessageListResponse,
  RequesterContextResponse,
  TicketHistoryListResponse,
  TicketResponse,
} from "@/lib/api/client";

// Доменные типы карточки выведены из контракта (только типовой импорт — server-only
// runtime клиента в клиентский бандл не тянется).
export type Ticket = NonNullable<TicketResponse["data"]>;
export type TicketMessage = NonNullable<MessageListResponse["data"]>[number];
export type TicketHistoryEntry = NonNullable<TicketHistoryListResponse["data"]>[number];
export type RequesterContextData = NonNullable<RequesterContextResponse["data"]>;

/**
 * Результат серверной загрузки контекста заявителя (#73). Объединение состояний
 * позволяет компоненту (и тестам) пройти все ветки: данные / 403 / ошибка. Флаг
 * `degraded` (интеграция platform не настроена, см. #77) живёт ВНУТРИ `context`.
 */
export type RequesterContextResult =
  | { context: RequesterContextData }
  | { forbidden: true }
  | { error: string };

/**
 * Результат мутирующего действия через server action. Ошибка пересекает границу
 * сервер→клиент только как `{status,title}` — `detail`/problem (потенц. ПДн) остаются
 * на сервере (ФЗ-152). 422 (недопустимый переход/валидация) и 409 (конфликт) — сюда же.
 */
export type ActionResult = { ok: true } | { ok: false; status: number; title: string };
