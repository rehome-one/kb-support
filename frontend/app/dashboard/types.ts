import type { SupportStatsResponse } from "@/lib/api/client";

/** Сводные метрики панели супервайзера (контракт `getSupportStats`, #166). */
export type SupportStats = NonNullable<SupportStatsResponse["data"]>;

/**
 * Результат загрузки статистики для панели (#170). Дискриминированный union, как
 * `RequesterContextResult` (#73): данные / 403 (не супервайзер) / ошибка. Токен
 * остаётся на сервере (server-only fetch в `page.tsx`).
 */
export type SupportStatsResult = { stats: SupportStats } | { forbidden: true } | { error: string };
