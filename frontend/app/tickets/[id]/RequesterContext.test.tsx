import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RequesterContext } from "./RequesterContext";
import type { RequesterContextData, Ticket } from "./types";

const ticket = (over: Partial<Ticket> = {}): Ticket =>
  ({
    id: "t1",
    number: "RH-2026-00042",
    requester_id: "req-aaaaaaaa-1111",
    premises_id: "prem-bbbb-2222",
    booking_id: "book-cccc-3333",
    ...over,
  }) as Ticket;

const fullContext = (over: Partial<RequesterContextData> = {}): RequesterContextData =>
  ({
    user: {
      id: "req-aaaaaaaa-1111",
      display_name: "Иван Заявитель",
      email: "ivan@example.com",
      phone: "+7 900 000-00-00",
      role: "tenant",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
    },
    premises: {
      id: "prem-bbbb-2222",
      address: "СПб, Невский пр., 1",
      kind: "apartment",
      rooms: 2,
      area_m2: 54,
      landlord_id: "ll-1",
    },
    booking: {
      id: "book-cccc-3333",
      premises_id: "prem-bbbb-2222",
      tenant_id: "req-aaaaaaaa-1111",
      landlord_id: "ll-1",
      status: "active",
      period_start: "2026-01-01",
      period_end: null,
      monthly_rent: 50000,
    },
    collaborator: {
      id: "col-1",
      name: "Клининг Сервис",
      category: "cleaning",
      contact: { email: "clean@example.com", phone: null },
      is_active: true,
    },
    degraded: false,
    ...over,
  }) as RequesterContextData;

describe("RequesterContext", () => {
  it("рендерит наполненные секции с лейблами и форматированием", () => {
    render(<RequesterContext ticket={ticket()} result={{ context: fullContext() }} />);
    expect(screen.getByText("Иван Заявитель")).toBeInTheDocument();
    expect(screen.getByText("Наниматель")).toBeInTheDocument(); // role label
    expect(screen.getByText("ivan@example.com")).toBeInTheDocument();
    expect(screen.getByText("СПб, Невский пр., 1")).toBeInTheDocument();
    expect(screen.getByText("Квартира")).toBeInTheDocument(); // kind label
    expect(screen.getByText("Активна")).toBeInTheDocument(); // booking status label
    expect(screen.getByText("50 000 ₽")).toBeInTheDocument(); // money
    expect(screen.getByText("Клининг Сервис")).toBeInTheDocument();
  });

  it("degraded=true: сообщение о ненастроенной интеграции + fallback на идентификаторы", () => {
    const ctx = fullContext({
      user: null,
      premises: null,
      booking: null,
      collaborator: null,
      degraded: true,
    });
    render(<RequesterContext ticket={ticket()} result={{ context: ctx }} />);
    expect(screen.getByText(/интеграция не настроена/i)).toBeInTheDocument();
    // id-fallback заявителя (первые 8 символов uuid).
    expect(screen.getByText("req-aaaa")).toBeInTheDocument();
  });

  it("частичный null: есть заявитель, нет объекта → объект через id-fallback", () => {
    const ctx = fullContext({ premises: null, booking: null, collaborator: null });
    render(<RequesterContext ticket={ticket()} result={{ context: ctx }} />);
    expect(screen.getByText("Иван Заявитель")).toBeInTheDocument(); // секция user жива
    expect(screen.getByText("prem-bbb")).toBeInTheDocument(); // premises id-fallback
  });

  it("ошибка загрузки → нейтральное сообщение (без detail)", () => {
    render(
      <RequesterContext
        ticket={ticket()}
        result={{ error: "Не удалось загрузить контекст заявителя" }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить контекст заявителя");
  });

  it("403 → нейтральная ветка «только операторам»", () => {
    render(<RequesterContext ticket={ticket()} result={{ forbidden: true }} />);
    expect(screen.getByText(/только операторам/i)).toBeInTheDocument();
  });
});
