import { ApiError, getSupportStats, type SupportStatsQuery } from "@/lib/api/client";

import type { SupportStatsResult } from "./types";

/** Берёт скалярное значение query-параметра (первый элемент массива); пустое → undefined. */
export function scalar(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.trim() ? v.trim() : undefined;
}

/**
 * Серверная загрузка сводных метрик панели (#170, #166). Токен на сервере.
 * Graceful degradation: 403 (не супервайзер) → нейтральная ветка; всё остальное
 * (включая 422 битого периода) → нейтральная ошибка без утечки detail (ФЗ-152).
 */
export async function loadStats(query: SupportStatsQuery): Promise<SupportStatsResult> {
  try {
    const res = await getSupportStats(query);
    // 200 контракта всегда несёт data; на всякий случай — мягкая деградация.
    return res.data ? { stats: res.data } : { error: "Статистика недоступна" };
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return { forbidden: true };
    }
    return { error: "Не удалось загрузить статистику" };
  }
}
