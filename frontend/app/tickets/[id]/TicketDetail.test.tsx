import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TicketDetail } from "./TicketDetail";
import type { Ticket } from "./types";

const ticket = (over: Partial<Ticket> = {}): Ticket =>
  ({
    id: "t1",
    number: "RH-2026-00042",
    subject: "Не работает отопление",
    status: "OPEN",
    priority: "high",
    type: "MAINTENANCE",
    channel: "EMAIL",
    assignee_id: null,
    team: "support",
    sla_breached: false,
    created_at: "2026-06-01T09:30:00Z",
    updated_at: "2026-06-01T10:00:00Z",
    resolution_due_at: "2026-06-02T09:30:00Z",
    description: "Холодные батареи",
    ...over,
  }) as Ticket;

describe("TicketDetail", () => {
  it("рендерит ключевые поля заявки", () => {
    render(<TicketDetail ticket={ticket()} />);
    expect(screen.getByText("RH-2026-00042")).toBeInTheDocument();
    expect(screen.getByText("Не работает отопление")).toBeInTheDocument();
    expect(screen.getByText("В работе")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument();
    expect(screen.getByText("Холодные батареи")).toBeInTheDocument();
  });

  it("«—» для отсутствующего исполнителя", () => {
    // sla_state задан, чтобы единственный «—» был у исполнителя (бейдж SLA не «—»).
    render(<TicketDetail ticket={ticket({ assignee_id: null, sla_state: "ok" })} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("не рендерит блок описания, если оно пустое", () => {
    render(<TicketDetail ticket={ticket({ description: undefined })} />);
    expect(screen.queryByText("Описание")).not.toBeInTheDocument();
  });

  it("показывает поле SLA с состоянием", () => {
    render(<TicketDetail ticket={ticket({ sla_state: "approaching" })} />);
    expect(screen.getByText("SLA")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "SLA: Скоро дедлайн" })).toBeInTheDocument();
  });

  it("показывает рейтинг с комментарием (read-only)", () => {
    render(<TicketDetail ticket={ticket({ rating: 4, rating_comment: "спасибо" })} />);
    expect(screen.getByText("Оценка качества")).toBeInTheDocument();
    expect(screen.getByText("4 / 5")).toBeInTheDocument();
    expect(screen.getByText("спасибо")).toBeInTheDocument();
  });

  it("показывает рейтинг без комментария", () => {
    render(<TicketDetail ticket={ticket({ rating: 5, rating_comment: null })} />);
    expect(screen.getByText("5 / 5")).toBeInTheDocument();
  });

  it("«не оценена» при отсутствии рейтинга", () => {
    render(<TicketDetail ticket={ticket({ rating: null })} />);
    expect(screen.getByText("не оценена")).toBeInTheDocument();
    expect(screen.queryByText(/\/ 5/)).not.toBeInTheDocument();
  });
});
