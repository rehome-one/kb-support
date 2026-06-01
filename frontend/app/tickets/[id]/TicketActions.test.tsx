import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { TicketActions } from "./TicketActions";
import type { ActionResult, Ticket } from "./types";

const ticket = (over: Partial<Ticket> = {}): Ticket =>
  ({
    id: "t1",
    number: "RH-1",
    subject: "S",
    status: "OPEN",
    priority: "normal",
    type: "OTHER",
    channel: "EMAIL",
    team: "support",
    tags: ["vip"],
    allowed_status_transitions: ["PENDING", "RESOLVED"],
    created_at: "2026-06-01T09:30:00Z",
    updated_at: "2026-06-01T09:30:00Z",
    ...over,
  }) as Ticket;

type Props = ComponentProps<typeof TicketActions>;
const okFn = () => vi.fn().mockResolvedValue({ ok: true } satisfies ActionResult);

function renderActions(over: Partial<Ticket> = {}, overrides: Partial<Props> = {}) {
  const props: Props = {
    ticket: ticket(over),
    patchAction: okFn(),
    assignAction: okFn(),
    escalateAction: okFn(),
    resolveAction: okFn(),
    closeAction: okFn(),
    reopenAction: okFn(),
    ...overrides,
  };
  render(<TicketActions {...props} />);
  return props;
}

describe("TicketActions — статус/PATCH", () => {
  it("select статуса предлагает только текущий + allowed_status_transitions", () => {
    renderActions();
    const select = screen.getByLabelText("Статус") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["OPEN", "PENDING", "RESOLVED"]);
  });

  it("смена статуса вызывает patchAction с {status}", async () => {
    const p = renderActions();
    fireEvent.change(screen.getByLabelText("Статус"), { target: { value: "RESOLVED" } });
    await waitFor(() => expect(p.patchAction).toHaveBeenCalledWith("t1", { status: "RESOLVED" }));
  });

  it("при отсутствии allowed_status_transitions не падает (только текущий статус)", () => {
    renderActions({ allowed_status_transitions: undefined });
    const select = screen.getByLabelText("Статус") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["OPEN"]);
  });

  it("смена приоритета вызывает patchAction", async () => {
    const p = renderActions();
    fireEvent.change(screen.getByLabelText("Приоритет"), { target: { value: "high" } });
    await waitFor(() => expect(p.patchAction).toHaveBeenCalledWith("t1", { priority: "high" }));
  });

  it("сохранение меток шлёт полный массив tags", async () => {
    const p = renderActions();
    fireEvent.change(screen.getByLabelText("Метки (через запятую)"), {
      target: { value: "vip, urgent" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить метки" }));
    await waitFor(() =>
      expect(p.patchAction).toHaveBeenCalledWith("t1", { tags: ["vip", "urgent"] }),
    );
  });
});

describe("TicketActions — действия", () => {
  it("assign требует assignee_id и шлёт его", async () => {
    const p = renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));
    fireEvent.change(screen.getByLabelText("Исполнитель (uuid)"), { target: { value: "u9" } });
    fireEvent.click(screen.getByRole("button", { name: "Назначить исполнителя" }));
    await waitFor(() => expect(p.assignAction).toHaveBeenCalledWith("t1", { assignee_id: "u9" }));
  });

  it("close — двухшаговое подтверждение → closeAction", async () => {
    const p = renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(p.closeAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() => expect(p.closeAction).toHaveBeenCalledWith("t1"));
  });

  it("reopen шлёт reason", async () => {
    const p = renderActions({ status: "CLOSED", allowed_status_transitions: ["REOPENED"] });
    fireEvent.click(screen.getByRole("button", { name: "Переоткрыть" }));
    fireEvent.change(screen.getByLabelText("Причина переоткрытия (необязательно)"), {
      target: { value: "повторное обращение" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Переоткрыть заявку" }));
    await waitFor(() =>
      expect(p.reopenAction).toHaveBeenCalledWith("t1", { reason: "повторное обращение" }),
    );
  });
});

describe("TicketActions — ошибки (409/422)", () => {
  it("422 (недопустимый переход) → алерт с текстом title", async () => {
    const patchAction = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      title: "Недопустимый переход статуса",
    } satisfies ActionResult);
    renderActions({}, { patchAction });
    fireEvent.change(screen.getByLabelText("Статус"), { target: { value: "RESOLVED" } });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Недопустимый переход статуса");
  });

  it("409 (конфликт) на действии → алерт", async () => {
    const escalateAction = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      title: "Конфликт состояния",
    } satisfies ActionResult);
    renderActions({}, { escalateAction });
    fireEvent.click(screen.getByRole("button", { name: "Эскалировать" }));
    fireEvent.click(screen.getByRole("button", { name: "Эскалировать на 2-ю линию" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Конфликт состояния");
  });
});

describe("TicketActions — RBAC", () => {
  it("кнопки rate нет (requester-only)", () => {
    renderActions();
    expect(screen.queryByRole("button", { name: /оцен/i })).not.toBeInTheDocument();
  });
});
