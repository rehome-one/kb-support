"use server";

import { ApiError, getReportCsv, type ReportQuery, type ReportType } from "@/lib/api/client";
import { UnauthenticatedError } from "@/lib/api/transport";

/** Результат CSV-выгрузки: строка + имя файла, либо фиксированная ошибка (detail не утекает). */
export type CsvResult = { csv: string; filename: string } | { error: string };

/**
 * Серверная CSV-выгрузка отчёта (#171, FR-7.2). Токен на сервере (server action);
 * клиент получает только строку CSV + имя файла и сам формирует Blob — токен в
 * браузер не уходит. Ошибки — фиксированные строки без `detail` (ФЗ-152).
 */
export async function downloadReportCsvAction(
  type: ReportType,
  from?: string,
  to?: string,
): Promise<CsvResult> {
  const query: ReportQuery = { from, to };
  try {
    const csv = await getReportCsv(type, query);
    const parts = ["report", type, from, to].filter(Boolean);
    return { csv, filename: `${parts.join("-")}.csv` };
  } catch (error) {
    if (error instanceof UnauthenticatedError) {
      return { error: "Сессия истекла. Войдите снова." };
    }
    if (error instanceof ApiError && error.status === 403) {
      return { error: "Отчёты доступны только супервайзеру." };
    }
    return { error: "Не удалось сформировать CSV" };
  }
}
