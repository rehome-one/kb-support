"use server";

import { ApiError, listTickets } from "@/lib/api/client";
import { UnauthenticatedError } from "@/lib/api/transport";

import type { ListTicketsQuery, LoadResult } from "./types";

/**
 * Серверная загрузка страницы списка заявок. Вызывает server-only `listTickets`
 * (Bearer из серверной сессии — токен в браузер не уходит). Используется и для
 * первой страницы (Server Component), и для «load more» (server action из клиента).
 *
 * Ошибки маппятся в `LoadResult.ok=false` и НЕ бросаются через границу: наружу
 * идут только `status`+`title`, `detail`/problem (потенц. ПДн) остаются на сервере.
 */
export async function loadTicketsPage(query: ListTicketsQuery): Promise<LoadResult> {
  try {
    const response = await listTickets(query);
    return {
      ok: true,
      rows: response.data ?? [],
      nextCursor: response.pagination?.next_cursor ?? null,
      hasMore: response.pagination?.has_more ?? false,
    };
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return {
        ok: false,
        status: 401,
        title: "Сессия истекла — войдите снова",
        unauthenticated: true,
      };
    }
    if (error instanceof ApiError) {
      return {
        ok: false,
        status: error.status,
        title: error.title,
        unauthenticated: error.status === 401,
      };
    }
    return { ok: false, status: 0, title: "Не удалось загрузить заявки", unauthenticated: false };
  }
}
