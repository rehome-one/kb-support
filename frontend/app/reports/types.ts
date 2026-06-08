import type { ReportResponse, ReportType } from "@/lib/api/client";

/** Типизированный отчёт (union по `report`-дискриминатору, контракт `getReport`, #167). */
export type Report = NonNullable<ReportResponse["data"]>;

/**
 * Результат загрузки отчёта (#171), как `SupportStatsResult` (#170): данные /
 * 403 (не супервайзер) / ошибка. Токен на сервере (server-only fetch).
 */
export type ReportResult = { report: Report } | { forbidden: true } | { error: string };

export type { ReportType };

/** Метки типов отчётов для селектора (FR-7.2). */
export const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  volume: "Объём заявок",
  sla: "Соблюдение SLA",
  satisfaction: "Удовлетворённость",
  reopens: "Повторные обращения",
  operators: "Эффективность операторов",
};

export const REPORT_TYPES = Object.keys(REPORT_TYPE_LABELS) as ReportType[];
