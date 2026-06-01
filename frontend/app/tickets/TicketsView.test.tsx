import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/tickets",
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { TicketsView } from "./TicketsView";
import type { LoadResult, TicketSummary } from "./types";

const ticket = (id: string, subject: string): TicketSummary => ({
  id,
  number: `RH-${id}`,
  subject,
  status: "OPEN",
  priority: "normal",
  type: "OTHER",
  channel: "EMAIL",
  created_at: "2026-06-01T09:30:00Z",
  sla_breached: false,
});

const okPage = (
  rows: TicketSummary[],
  nextCursor: string | null,
  hasMore: boolean,
): LoadResult => ({
  ok: true,
  rows,
  nextCursor,
  hasMore,
});

beforeEach(() => {
  replace.mockClear();
});

describe("TicketsView — пагинация", () => {
  it("«Показать ещё» добавляет страницу, дедуплицирует по id, прячет кнопку в конце", async () => {
    const initial = okPage([ticket("a", "Первая"), ticket("b", "Вторая")], "c1", true);
    // Вторая страница пересекается по id "b" — дубль не должен попасть в список.
    const loadMore = vi
      .fn()
      .mockResolvedValue(okPage([ticket("b", "Вторая"), ticket("c", "Третья")], null, false));

    render(<TicketsView query={{}} initial={initial} loadMore={loadMore} />);
    fireEvent.click(screen.getByRole("button", { name: "Показать ещё" }));

    await waitFor(() => expect(screen.getByText("Третья")).toBeInTheDocument());
    expect(loadMore).toHaveBeenCalledWith({ cursor: "c1" });
    expect(screen.getAllByText("Вторая")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Показать ещё/ })).not.toBeInTheDocument();
  });

  it("401 при подгрузке → алерт со ссылкой на вход", async () => {
    const initial = okPage([ticket("a", "Первая")], "c1", true);
    const loadMore = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      title: "Сессия истекла",
      unauthenticated: true,
    } satisfies LoadResult);

    render(<TicketsView query={{}} initial={initial} loadMore={loadMore} />);
    fireEvent.click(screen.getByRole("button", { name: "Показать ещё" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Сессия истекла");
    expect(screen.getByRole("link", { name: "Войти снова" })).toBeInTheDocument();
  });
});

describe("TicketsView — фильтры", () => {
  it("смена фильтра вызывает router.replace с обновлённым запросом", () => {
    render(<TicketsView query={{}} initial={okPage([], null, false)} loadMore={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Статус"), { target: { value: "OPEN" } });
    expect(replace).toHaveBeenCalledWith("/tickets?status=OPEN");
  });
});

describe("TicketsView — состояния", () => {
  it("пустой результат → сообщение «не найдено»", () => {
    render(<TicketsView query={{}} initial={okPage([], null, false)} loadMore={vi.fn()} />);
    expect(screen.getByText("Заявок не найдено.")).toBeInTheDocument();
  });

  it("ошибка первой загрузки → алерт", () => {
    render(
      <TicketsView
        query={{}}
        initial={{
          ok: false,
          status: 0,
          title: "Не удалось загрузить заявки",
          unauthenticated: false,
        }}
        loadMore={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить заявки");
  });
});
