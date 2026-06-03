import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

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

  it("показывает бейдж состояния SLA с цветом по состоянию", () => {
    const { rerender } = render(<TicketsTable rows={[ticket({ sla_state: "breached" })]} />);
    const breached = screen.getByRole("status", { name: "SLA: Нарушен" });
    expect(breached).toHaveClass("text-red-600");

    rerender(<TicketsTable rows={[ticket({ sla_state: "approaching" })]} />);
    expect(screen.getByRole("status", { name: "SLA: Скоро дедлайн" })).toHaveClass(
      "text-amber-500",
    );

    rerender(<TicketsTable rows={[ticket({ sla_state: "ok" })]} />);
    expect(screen.getByRole("status", { name: "SLA: OK" })).toHaveClass("text-green-600");
  });

  it("не показывает индикатор SLA для none/отсутствия состояния", () => {
    const { rerender } = render(<TicketsTable rows={[ticket({ sla_state: "none" })]} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    rerender(<TicketsTable rows={[ticket()]} />); // sla_state отсутствует
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
