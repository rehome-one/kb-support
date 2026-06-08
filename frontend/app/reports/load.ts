import { ApiError, getReport, type ReportQuery, type ReportType } from "@/lib/api/client";

import type { ReportResult } from "./types";

/** Скаляр query-параметра (первый элемент массива); пустое → undefined (дефолт бэкенда). */
export function scalar(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.trim() ? v.trim() : undefined;
}

/**
 * Серверная загрузка типизированного отчёта (#171, #167). Токен на сервере.
 * Graceful: 403 (не супервайзер) → нейтральная ветка; прочее (вкл. 422 битого
 * периода) → нейтральная ошибка без утечки detail (ФЗ-152).
 */
export async function loadReport(type: ReportType, query: ReportQuery): Promise<ReportResult> {
  try {
    const res = await getReport(type, query);
    return res.data ? { report: res.data } : { error: "Отчёт недоступен" };
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return { forbidden: true };
    }
    return { error: "Не удалось загрузить отчёт" };
  }
}
