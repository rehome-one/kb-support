import { OperatorHeader } from "@/app/components/OperatorHeader";
import type { ReportType } from "@/lib/api/client";

import { loadReport, scalar } from "./load";
import { ReportControls } from "./ReportControls";
import { ReportTable } from "./ReportTable";
import { REPORT_TYPES } from "./types";

interface PageProps {
  searchParams: Record<string, string | string[] | undefined>;
}

/** Тип отчёта из URL; неизвестный/отсутствующий → дефолт `volume`. */
function parseType(value: string | string[] | undefined): ReportType {
  const v = scalar(value);
  return v && (REPORT_TYPES as string[]).includes(v) ? (v as ReportType) : "volume";
}

/**
 * Страница отчётов (E8-7, FR-7.2). Server Component: тип/период из URL, серверный
 * fetch отчёта (токен на сервере), graceful degradation. Гейт супервайзера — на
 * бэкенде (#167): 403 → нейтральная ветка. Маршрут защищён middleware.
 */
export default async function ReportsPage({ searchParams }: PageProps) {
  const type = parseType(searchParams.type);
  const from = scalar(searchParams.from);
  const to = scalar(searchParams.to);
  const result = await loadReport(type, { from, to });

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 p-8">
      <OperatorHeader />
      <section className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold">Отчёты</h1>
        <ReportControls type={type} from={from} to={to} />

        {"forbidden" in result ? (
          <p className="text-sm text-gray-500">
            Отчёты доступны только пользователям с правом просмотра аналитики.
          </p>
        ) : "error" in result ? (
          <p role="alert" className="text-sm text-red-600">
            {result.error}
          </p>
        ) : (
          <div className="overflow-x-auto rounded border border-gray-200">
            <ReportTable report={result.report} />
          </div>
        )}
      </section>
    </main>
  );
}
