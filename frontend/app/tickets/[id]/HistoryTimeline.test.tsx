import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HistoryTimeline } from "./HistoryTimeline";
import type { TicketHistoryEntry } from "./types";

const entry = (over: Partial<TicketHistoryEntry> = {}): TicketHistoryEntry => ({
  id: "h1",
  ticket_id: "t1",
  actor_id: "11111111-2222-3333-4444-555555555555",
  action: "status_changed",
  from_value: { status: "NEW" },
  to_value: { status: "OPEN" },
  created_at: "2026-06-01T09:30:00Z",
  ...over,
});

describe("HistoryTimeline", () => {
  it("рендерит запись с лейблом действия и diff", () => {
    render(<HistoryTimeline entries={[entry()]} />);
    expect(screen.getByText("Смена статуса")).toBeInTheDocument();
    expect(screen.getByText("status: NEW → status: OPEN")).toBeInTheDocument();
  });

  it("created (from_value=null) рендерится без diff-стрелки слева", () => {
    render(
      <HistoryTimeline
        entries={[
          entry({ id: "h0", action: "created", from_value: null, to_value: { status: "NEW" } }),
        ]}
      />,
    );
    expect(screen.getByText("Создана")).toBeInTheDocument();
    expect(screen.getByText("→ status: NEW")).toBeInTheDocument();
  });

  it("message_added (служебный объект) не роняет рендер", () => {
    render(
      <HistoryTimeline
        entries={[
          entry({
            id: "h2",
            action: "message_added",
            from_value: null,
            to_value: { message_id: "m1", is_internal: false },
          }),
        ]}
      />,
    );
    expect(screen.getByText("Добавлено сообщение")).toBeInTheDocument();
  });

  it("сохраняет порядок записей как пришёл (обратный хронологический)", () => {
    render(
      <HistoryTimeline
        entries={[entry({ id: "h2", action: "rated" }), entry({ id: "h1", action: "created" })]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Оценка");
    expect(items[1]).toHaveTextContent("Создана");
  });

  it("пустая история → заглушка", () => {
    render(<HistoryTimeline entries={[]} />);
    expect(screen.getByText("История пуста.")).toBeInTheDocument();
  });
});
