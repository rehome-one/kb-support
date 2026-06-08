import { OperatorHeader } from "@/app/components/OperatorHeader";

import { loadStats, scalar } from "./load";
import { PeriodSelector } from "./PeriodSelector";
import { StatsSections } from "./StatsSections";

interface PageProps {
  searchParams: Record<string, string | string[] | undefined>;
}

/**
 * Панель супервайзера (E8-6, FR-7.1). Server Component: разбирает период из URL,
 * серверно тянет сводные метрики (токен из сессии не уходит в браузер), graceful
 * degradation (см. `load.ts`). Гейт супервайзера — на бэкенде (#166): 403 →
 * нейтральная ветка. Маршрут защищён middleware (аутентификация).
 */
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
