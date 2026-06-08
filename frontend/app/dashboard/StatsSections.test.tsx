import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatsSections } from "./StatsSections";
import type { SupportStats } from "./types";

const fullStats = (over: Partial<SupportStats> = {}): SupportStats => ({
  period: { from: "2026-05-09", to: "2026-06-08" },
  tickets: {
    total: 120,
    open: 14,
    resolved: 90,
    closed: 16,
    by_type: { PAYMENT: 70, COMPLAINT: 50 },
    by_channel: { WEB_FORM: 80, EMAIL: 40 },
  },
  sla: {
    first_response_compliance_pct: 92.5,
    resolution_compliance_pct: 88,
    breaches: 7,
  },
  performance: {
    avg_first_response_minutes: 12.4,
    avg_resolution_minutes: 240.9,
    reopened_rate_pct: 3.1,
  },
  quality: { avg_rating: 4.37, ratings_count: 53 },
  ai_chat: { containment_rate_pct: 61.2, escalated_count: 19, degraded: false },
  ...over,
});

describe("StatsSections", () => {
  it("рендерит все секции из полного ответа", () => {
    render(<StatsSections result={{ stats: fullStats() }} />);
    expect(screen.getByText("Заявки")).toBeInTheDocument();
    expect(screen.getByText("SLA")).toBeInTheDocument();
    expect(screen.getByText("Производительность")).toBeInTheDocument();
    expect(screen.getByText("Качество")).toBeInTheDocument();
    expect(screen.getByText("Первая линия (AI-чат)")).toBeInTheDocument();
    // конкретные значения
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("92.5%")).toBeInTheDocument();
    expect(screen.getByText("4.37")).toBeInTheDocument();
    expect(screen.getByText("61.2%")).toBeInTheDocument();
    // период
    expect(screen.getByText(/Период:/)).toHaveTextContent("2026");
  });

  it("разбивки по типу и каналу используют человекочитаемые лейблы", () => {
    render(<StatsSections result={{ stats: fullStats() }} />);
    expect(screen.getByText("По типу")).toBeInTheDocument();
    expect(screen.getByText("По каналу")).toBeInTheDocument();
    // лейблы из format.ts, не сырые enum
    expect(screen.getByText("Оплата")).toBeInTheDocument();
    expect(screen.getByText("Веб-форма")).toBeInTheDocument();
    expect(screen.queryByText("PAYMENT")).not.toBeInTheDocument();
  });

  it("degraded ai_chat → сообщение о недоступности, без containment-плиток", () => {
    render(<StatsSections result={{ stats: fullStats({ ai_chat: { degraded: true } }) }} />);
    expect(screen.getByText(/интеграция kb-search не настроена/i)).toBeInTheDocument();
    expect(screen.queryByText("Containment (без эскалации)")).not.toBeInTheDocument();
  });

  it("nullable-поля рендерятся как «—», страница не падает", () => {
    render(
      <StatsSections
        result={{
          stats: fullStats({
            sla: {
              first_response_compliance_pct: null,
              resolution_compliance_pct: null,
              breaches: 0,
            },
            performance: {
              avg_first_response_minutes: null,
              avg_resolution_minutes: null,
              reopened_rate_pct: null,
            },
            quality: { avg_rating: null, ratings_count: 0 },
            ai_chat: { containment_rate_pct: null, escalated_count: 0, degraded: false },
          }),
        }}
      />,
    );
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("403 → нейтральная ветка «только супервайзеру»", () => {
    render(<StatsSections result={{ forbidden: true }} />);
    expect(
      screen.getByText(/только пользователям с правом просмотра аналитики/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Заявки")).not.toBeInTheDocument();
  });

  it("ошибка → фиксированная строка в role=alert, без секций", () => {
    render(<StatsSections result={{ error: "Не удалось загрузить статистику" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить статистику");
    expect(screen.queryByText("Заявки")).not.toBeInTheDocument();
  });
});
