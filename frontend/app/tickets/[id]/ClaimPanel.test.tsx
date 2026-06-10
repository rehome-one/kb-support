import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClaimPanel } from "./ClaimPanel";
import type { Ticket } from "./types";

const ticket = (over: Partial<Ticket> = {}): Ticket =>
  ({
    id: "t1",
    number: "RH-9",
    subject: "Залив соседей",
    status: "OPEN",
    priority: "high",
    type: "COMPENSATION",
    channel: "LK_CLAIM",
    created_at: "2026-06-01T09:30:00Z",
    updated_at: "2026-06-01T09:30:00Z",
    case_state: "UNDER_REVIEW",
    claim_amount: 50000,
    approved_amount: null,
    decision: null,
    decision_reason: null,
    decision_notified_at: null,
    payout_due_at: null,
    linked_payment_id: null,
    case_details: null,
    ...over,
  }) as Ticket;

describe("ClaimPanel — состояние и суммы", () => {
  it("показывает лейбл case_state и сумму претензии", () => {
    render(<ClaimPanel ticket={ticket()} />);
    expect(screen.getByText("На рассмотрении")).toBeInTheDocument();
    expect(screen.getByText("50 000 ₽")).toBeInTheDocument();
  });

  it("case_state=null → «—» (claims-заявка без присвоенного состояния)", () => {
    render(<ClaimPanel ticket={ticket({ case_state: null })} />);
    // Панель не падает; поле «Состояние» присутствует, значение деградирует к «—».
    const stateField = screen.getByText("Состояние").closest("div");
    expect(stateField).toHaveTextContent("—");
  });
});

describe("ClaimPanel — решение", () => {
  it("без решения показывает заглушку", () => {
    render(<ClaimPanel ticket={ticket()} />);
    expect(screen.getByText("решение ещё не принято")).toBeInTheDocument();
  });

  it("с решением показывает вердикт и мотивировку", () => {
    render(
      <ClaimPanel
        ticket={ticket({
          decision: "PARTIAL",
          approved_amount: 30000,
          decision_reason: "Износ учтён",
        })}
      />,
    );
    expect(screen.getByText("Частичное удовлетворение")).toBeInTheDocument();
    expect(screen.getByText("Износ учтён")).toBeInTheDocument();
    expect(screen.getByText("30 000 ₽")).toBeInTheDocument();
  });
});

describe("ClaimPanel — аудит выплаты", () => {
  it("без платежа — «ожидается»", () => {
    render(<ClaimPanel ticket={ticket()} />);
    expect(screen.getByText("ожидается")).toBeInTheDocument();
  });

  it("с linked_payment_id — короткий id", () => {
    render(
      <ClaimPanel ticket={ticket({ linked_payment_id: "abcdef12-3456-7890-aaaa-bbbbbbbbbbbb" })} />,
    );
    expect(screen.getByText("abcdef12")).toBeInTheDocument();
  });
});

describe("ClaimPanel — детали кейса", () => {
  it("рендерит case_type/act_kind/signing_status и payload нейтрально", () => {
    render(
      <ClaimPanel
        ticket={ticket({
          type: "ACCEPTANCE_ACT",
          case_details: {
            case_type: "ACCEPTANCE_ACT",
            act_kind: "MOVE_OUT",
            signing_status: "disputed",
            payload: { blocked_payment_id: "p-1" },
          },
        } as Partial<Ticket>)}
      />,
    );
    expect(screen.getByText("Акт приёма")).toBeInTheDocument();
    expect(screen.getByText("Акт выселения")).toBeInTheDocument();
    expect(screen.getByText("Оспаривается")).toBeInTheDocument();
    // payload — ключ и значение без доменной интерпретации.
    expect(screen.getByText("blocked_payment_id")).toBeInTheDocument();
    expect(screen.getByText("p-1")).toBeInTheDocument();
  });
});
