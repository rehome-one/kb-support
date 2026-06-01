import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TicketsTable } from "./TicketsTable";
import type { TicketSummary } from "./types";

const ticket = (over: Partial<TicketSummary> = {}): TicketSummary => ({
  id: "id-1",
  number: "RH-2026-00042",
  subject: "Не работает отопление",
  status: "OPEN",
  priority: "high",
  type: "MAINTENANCE",
  channel: "EMAIL",
  created_at: "2026-06-01T09:30:00Z",
  sla_breached: false,
  ...over,
});

describe("TicketsTable", () => {
  it("рендерит колонки и значения строки", () => {
    render(<TicketsTable rows={[ticket()]} />);
    for (const col of [
      "Номер",
      "Тема",
      "Статус",
      "Приоритет",
      "Тип",
      "Исполнитель",
      "Команда",
      "Создана",
      "SLA",
    ]) {
      expect(screen.getByRole("columnheader", { name: col })).toBeInTheDocument();
    }
    expect(screen.getByText("RH-2026-00042")).toBeInTheDocument();
    expect(screen.getByText("Не работает отопление")).toBeInTheDocument();
    expect(screen.getByText("В работе")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument();
  });

  it("показывает индикатор SLA только при нарушении", () => {
    const { rerender } = render(<TicketsTable rows={[ticket({ sla_breached: true })]} />);
    expect(screen.getByRole("status", { name: "SLA нарушен" })).toBeInTheDocument();

    rerender(<TicketsTable rows={[ticket({ sla_breached: false })]} />);
    expect(screen.queryByRole("status", { name: "SLA нарушен" })).not.toBeInTheDocument();
  });
});
