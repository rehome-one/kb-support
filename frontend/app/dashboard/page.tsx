import { OperatorHeader } from "@/app/components/OperatorHeader";
import { ApiError, getSupportStats, type SupportStatsQuery } from "@/lib/api/client";

import { PeriodSelector } from "./PeriodSelector";
import { StatsSections } from "./StatsSections";
import type { SupportStatsResult } from "./types";

interface PageProps {
  searchParams: Record<string, string | string[] | undefined>;
}

/** Берёт скалярное значение query-параметра (первый элемент массива), пустое → undefined. */
function scalar(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.trim() ? v.trim() : undefined;
}

/**
 * Панель супервайзера (E8-6, FR-7.1). Server Component: разбирает период из URL,
 * серверно тянет сводные метрики (токен из сессии не уходит в браузер), graceful
 * degradation. Гейт супервайзера — на бэкенде (#166): 403 → нейтральная ветка.
 * Маршрут защищён middleware (аутентификация).
 */
async function loadStats(query: SupportStatsQuery): Promise<SupportStatsResult> {
  try {
    const res = await getSupportStats(query);
    // 200 контракта всегда несёт data; на всякий случай — мягкая деградация.
    return res.data ? { stats: res.data } : { error: "Статистика недоступна" };
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return { forbidden: true };
    }
    // Прочее (включая 422 битого периода) — нейтральная ошибка без утечки detail.
    return { error: "Не удалось загрузить статистику" };
  }
}

export default async function DashboardPage({ searchParams }: PageProps) {
  const from = scalar(searchParams.from);
  const to = scalar(searchParams.to);
  const result = await loadStats({ from, to });

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 p-8">
      <OperatorHeader />
      <section className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold">Панель супервайзера</h1>
        <PeriodSelector from={from} to={to} />
        <StatsSections result={result} />
      </section>
    </main>
  );
}
