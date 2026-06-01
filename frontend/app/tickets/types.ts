import type { ListTicketsQuery, TicketListResponse } from "@/lib/api/client";

// Краткая карточка заявки выводится из контракта (TicketListResponse.data[number]) —
// импорт только типовой, runtime server-only клиента в клиентский бандл не тянется.
export type TicketSummary = NonNullable<TicketListResponse["data"]>[number];

export type { ListTicketsQuery };

/** Одна страница списка для UI: строки + курсор следующей. */
export interface TicketsPage {
  rows: TicketSummary[];
  nextCursor: string | null;
  hasMore: boolean;
}

/**
 * Результат загрузки страницы через server action. Дискриминированный союз —
 * ошибки пересекают границу сервер→клиент только как `{status,title}`; `detail`
 * и полный problem (потенц. ПДн) за границу не уходят (инвариант ФЗ-152).
 */
export type LoadResult =
  | ({ ok: true } & TicketsPage)
  | { ok: false; status: number; title: string; unauthenticated: boolean };
