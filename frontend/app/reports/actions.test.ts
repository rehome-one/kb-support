import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, getReportCsv: vi.fn() };
});

import { ApiError, getReportCsv } from "@/lib/api/client";
import { UnauthenticatedError } from "@/lib/api/transport";

import { downloadReportCsvAction } from "./actions";

const mockCsv = vi.mocked(getReportCsv);

describe("downloadReportCsvAction", () => {
  it("успех → { csv, filename } с типом и периодом в имени", async () => {
    mockCsv.mockResolvedValue("dimension,key,count\n");
    const result = await downloadReportCsvAction("volume", "2026-05-01", "2026-05-31");
    expect(result).toEqual({
      csv: "dimension,key,count\n",
      filename: "report-volume-2026-05-01-2026-05-31.csv",
    });
  });

  it("без периода → имя только из типа", async () => {
    mockCsv.mockResolvedValue("x\n");
    const result = await downloadReportCsvAction("sla");
    expect(result).toEqual({ csv: "x\n", filename: "report-sla.csv" });
  });

  it("403 → фиксированная ошибка, без утечки detail", async () => {
    mockCsv.mockImplementation(() => {
      throw new ApiError(403, "Forbidden");
    });
    const result = await downloadReportCsvAction("operators");
    expect(result).toEqual({ error: "Отчёты доступны только супервайзеру." });
    expect(JSON.stringify(result)).not.toContain("Forbidden");
  });

  it("UnauthenticatedError → просьба войти", async () => {
    mockCsv.mockImplementation(() => {
      throw new UnauthenticatedError();
    });
    const result = await downloadReportCsvAction("volume");
    expect(result).toEqual({ error: "Сессия истекла. Войдите снова." });
  });

  it("прочая ошибка → нейтральная строка", async () => {
    mockCsv.mockImplementation(() => {
      throw new Error("boom");
    });
    const result = await downloadReportCsvAction("reopens");
    expect(result).toEqual({ error: "Не удалось сформировать CSV" });
  });
});
