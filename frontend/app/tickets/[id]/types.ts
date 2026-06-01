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
