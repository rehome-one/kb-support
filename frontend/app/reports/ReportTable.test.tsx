import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportTable } from "./ReportTable";
import type { Report } from "./types";

describe("ReportTable", () => {
  it("volume: обе ветки dimension (type → TYPE_LABELS, channel → CHANNEL_LABELS)", () => {
    const report: Report = {
      report: "volume",
      rows: [
        { dimension: "type", key: "PAYMENT", count: 12 },
        { dimension: "channel", key: "WEB_FORM", count: 7 },
      ],
    };
    render(<ReportTable report={report} />);
    expect(screen.getByText("Оплата")).toBeInTheDocument(); // TYPE_LABELS
    expect(screen.getByText("Веб-форма")).toBeInTheDocument(); // CHANNEL_LABELS
    expect(screen.getByText("Тип")).toBeInTheDocument();
    expect(screen.getByText("Канал")).toBeInTheDocument();
  });

  it("sla: nullable compliance → «—»", () => {
    const report: Report = {
      report: "sla",
      rows: [{ first_response_compliance_pct: null, resolution_compliance_pct: 90, breaches: 3 }],
    };
    render(<ReportTable report={report} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("90.0%")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("satisfaction: оценка/количество", () => {
    const report: Report = { report: "satisfaction", rows: [{ rating: 5, count: 21 }] };
    render(<ReportTable report={report} />);
    expect(screen.getByText("Оценка")).toBeInTheDocument();
    expect(screen.getByText("21")).toBeInTheDocument();
  });

  it("reopens: доля переоткрытий", () => {
    const report: Report = {
      report: "reopens",
      rows: [{ total: 100, reopened: 4, reopened_rate_pct: 4 }],
    };
    render(<ReportTable report={report} />);
    expect(screen.getByText("4.0%")).toBeInTheDocument();
  });

  it("operators: operator_id усечён (shortId), avg nullable → «—»", () => {
    const report: Report = {
      report: "operators",
      rows: [
        {
          operator_id: "abcdef12-3456-7890-aaaa-bbbbbbbbbbbb",
          resolved_count: 8,
          avg_resolution_minutes: null,
        },
      ],
    };
    render(<ReportTable report={report} />);
    // полный uuid не отображается как текст ячейки (усечён shortId)
    expect(screen.queryByText("abcdef12-3456-7890-aaaa-bbbbbbbbbbbb")).not.toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("пустые rows → строка «нет данных за период»", () => {
    const report: Report = { report: "volume", rows: [] };
    render(<ReportTable report={report} />);
    expect(screen.getByText("нет данных за период")).toBeInTheDocument();
  });
});
