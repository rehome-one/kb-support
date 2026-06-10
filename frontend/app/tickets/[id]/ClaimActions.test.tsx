import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { ClaimActions } from "./ClaimActions";
import type { ActionResult, Ticket } from "./types";

const ticket = (over: Partial<Ticket> = {}): Ticket =>
  ({
    id: "t1",
    number: "RH-9",
    subject: "S",
    status: "OPEN",
    priority: "high",
    type: "COMPENSATION",
    channel: "LK_CLAIM",
    case_state: "UNDER_REVIEW",
    decision: null,
    allowed_case_transitions: ["INSPECTION", "DECISION_MADE", "REJECTED"],
    created_at: "2026-06-01T09:30:00Z",
    updated_at: "2026-06-01T09:30:00Z",
    ...over,
  }) as Ticket;

type Props = ComponentProps<typeof ClaimActions>;
const okFn = () => vi.fn().mockResolvedValue({ ok: true } satisfies ActionResult);

function renderActions(over: Partial<Ticket> = {}, overrides: Partial<Props> = {}) {
  const props: Props = {
    ticket: ticket(over),
    decideAction: okFn(),
    transitionCaseStateAction: okFn(),
    ...overrides,
  };
  render(<ClaimActions {...props} />);
  return props;
}

describe("ClaimActions — переход case_state", () => {
  it("select содержит только allowed_case_transitions (+ плейсхолдер)", () => {
    renderActions();
    const select = screen.getByLabelText("Новое состояние") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual([
      "",
      "INSPECTION",
      "DECISION_MADE",
      "REJECTED",
    ]);
  });

  it("переход вызывает action с {case_state} и note при наличии", async () => {
    const p = renderActions();
    fireEvent.change(screen.getByLabelText("Новое состояние"), {
      target: { value: "INSPECTION" },
    });
    fireEvent.change(screen.getByLabelText("Комментарий (необязательно)"), {
      target: { value: "выезд назначен" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сменить состояние" }));
    await waitFor(() =>
      expect(p.transitionCaseStateAction).toHaveBeenCalledWith("t1", {
        case_state: "INSPECTION",
        note: "выезд назначен",
      }),
    );
  });

  it("пустой allowed_case_transitions → нет select, сообщение о завершении", () => {
    renderActions({ allowed_case_transitions: [] });
    expect(screen.queryByLabelText("Новое состояние")).not.toBeInTheDocument();
    expect(screen.getByText("Нет доступных переходов состояния.")).toBeInTheDocument();
  });

  it("отсутствие поля allowed_case_transitions не роняет компонент", () => {
    renderActions({ allowed_case_transitions: undefined });
    expect(screen.getByText("Нет доступных переходов состояния.")).toBeInTheDocument();
  });
});

describe("ClaimActions — решение", () => {
  it("форма решения видна, пока решение не принято", () => {
    renderActions();
    expect(screen.getByLabelText("Вердикт")).toBeInTheDocument();
  });

  it("уже принятое решение скрывает форму и показывает вердикт", () => {
    renderActions({ decision: "FULL" });
    expect(screen.queryByLabelText("Вердикт")).not.toBeInTheDocument();
    expect(screen.getByText(/Решение уже принято/)).toBeInTheDocument();
    expect(screen.getByText(/Полное удовлетворение/)).toBeInTheDocument();
  });

  it("submit заблокирован, пока FULL без суммы; разблокируется с суммой", () => {
    renderActions();
    fireEvent.change(screen.getByLabelText("Вердикт"), { target: { value: "FULL" } });
    const submit = screen.getByRole("button", { name: "Зафиксировать решение" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Одобренная сумма/), { target: { value: "50000" } });
    expect(submit).toBeEnabled();
  });

  it("REJECTED без мотивировки заблокирован; с мотивировкой шлёт {decision, reason}", async () => {
    const p = renderActions();
    fireEvent.change(screen.getByLabelText("Вердикт"), { target: { value: "REJECTED" } });
    const submit = screen.getByRole("button", { name: "Зафиксировать решение" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Мотивировка/), { target: { value: "вне покрытия" } });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(p.decideAction).toHaveBeenCalledWith("t1", {
        decision: "REJECTED",
        reason: "вне покрытия",
      }),
    );
  });

  it("смена вердикта сбрасывает сумму и мотивировку (нет стейл-значений)", () => {
    renderActions();
    fireEvent.change(screen.getByLabelText("Вердикт"), { target: { value: "FULL" } });
    fireEvent.change(screen.getByLabelText(/Одобренная сумма/), { target: { value: "50000" } });
    fireEvent.change(screen.getByLabelText("Вердикт"), { target: { value: "REJECTED" } });
    expect((screen.getByLabelText(/Одобренная сумма/) as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(/Мотивировка/) as HTMLInputElement).value).toBe("");
  });

  it("ошибка action (409/422) показывается как title без detail", async () => {
    const p = renderActions(
      {},
      {
        decideAction: vi
          .fn()
          .mockResolvedValue({ ok: false, status: 409, title: "Решение уже зафиксировано" }),
      },
    );
    fireEvent.change(screen.getByLabelText("Вердикт"), { target: { value: "FULL" } });
    fireEvent.change(screen.getByLabelText(/Одобренная сумма/), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: "Зафиксировать решение" }));
    await waitFor(() => expect(p.decideAction).toHaveBeenCalled());
    expect(screen.getByRole("alert")).toHaveTextContent("Решение уже зафиксировано");
  });
});
