"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { TicketFilters } from "./TicketFilters";
import { TicketsTable } from "./TicketsTable";
import { toSearchString } from "./query";
import type { ListTicketsQuery, LoadResult, TicketSummary } from "./types";

interface Props {
  /** Запрос (фильтры/sort) из URL — применённое состояние. */
  query: ListTicketsQuery;
  /** Первая страница, загруженная сервером. */
  initial: LoadResult;
  /** Server action подгрузки страницы (токен остаётся на сервере). */
  loadMore: (query: ListTicketsQuery) => Promise<LoadResult>;
}

interface ErrorState {
  title: string;
  unauthenticated: boolean;
}

const dedupeAppend = (rows: TicketSummary[], next: TicketSummary[]): TicketSummary[] => {
  const seen = new Set(rows.map((r) => r.id));
  return [...rows, ...next.filter((r) => !seen.has(r.id))];
};

export function TicketsView({ query, initial, loadMore }: Props) {
  const router = useRouter();
  const pathname = usePathname();

  const [rows, setRows] = useState<TicketSummary[]>(initial.ok ? initial.rows : []);
  const [cursor, setCursor] = useState<string | null>(initial.ok ? initial.nextCursor : null);
  const [hasMore, setHasMore] = useState<boolean>(initial.ok ? initial.hasMore : false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ErrorState | null>(
    initial.ok ? null : { title: initial.title, unauthenticated: initial.unauthenticated },
  );

  const applyFilters = (next: ListTicketsQuery) => {
    const qs = toSearchString(next);
    // Смена фильтров идёт через URL: Server Component перезагружает первую
    // страницу, а remount по key={queryKey} в page.tsx пересоздаёт этот
    // компонент со свежим состоянием — устаревший «load more» отбрасывается
    // вместе со старым инстансом, отдельный anti-stale guard не нужен.
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  };

  const handleLoadMore = async () => {
    if (loading || !hasMore || !cursor) return;
    setLoading(true);
    setError(null);
    const result = await loadMore({ ...query, cursor });
    setLoading(false);
    if (result.ok) {
      setRows((prev) => dedupeAppend(prev, result.rows));
      setCursor(result.nextCursor);
      setHasMore(result.hasMore);
    } else {
      setError({ title: result.title, unauthenticated: result.unauthenticated });
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <TicketFilters value={query} onChange={applyFilters} disabled={loading} />

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error.title}
          {error.unauthenticated && (
            <>
              {" "}
              <Link href="/login" className="underline">
                Войти снова
              </Link>
            </>
          )}
        </div>
      )}

      {rows.length === 0 && !error ? (
        <p className="text-sm text-gray-500">Заявок не найдено.</p>
      ) : (
        <TicketsTable rows={rows} />
      )}

      {hasMore && (
        <div>
          <button
            type="button"
            onClick={handleLoadMore}
            disabled={loading}
            className="rounded border border-gray-300 px-4 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            {loading ? "Загрузка…" : "Показать ещё"}
          </button>
        </div>
      )}
    </div>
  );
}
