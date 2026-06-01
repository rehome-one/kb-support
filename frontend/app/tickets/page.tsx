import { OperatorHeader } from "@/app/components/OperatorHeader";

import { TicketsView } from "./TicketsView";
import { loadTicketsPage } from "./actions";
import { parseQuery, queryKey } from "./query";

interface PageProps {
  searchParams: Record<string, string | string[] | undefined>;
}

/**
 * Экран «список заявок» (E2-4, FR-2.1). Server Component: разбирает фильтры из
 * URL, серверно тянет первую страницу (токен из сессии не уходит в браузер) и
 * отдаёт клиентскому `TicketsView`. Маршрут защищён middleware.
 */
export default async function TicketsPage({ searchParams }: PageProps) {
  const query = parseQuery(searchParams);
  const initial = await loadTicketsPage(query);

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 p-8">
      <OperatorHeader />
      <section className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold">Заявки</h1>
        {/* key=queryKey: смена фильтров пересоздаёт компонент со свежим состоянием. */}
        <TicketsView
          key={queryKey(query)}
          query={query}
          initial={initial}
          loadMore={loadTicketsPage}
        />
      </section>
    </main>
  );
}
