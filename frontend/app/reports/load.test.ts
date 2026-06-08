import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, getReport: vi.fn() };
});

import { ApiError, getReport } from "@/lib/api/client";

import { loadReport, scalar } from "./load";

const mockReport = vi.mocked(getReport);

describe("scalar", () => {
  it("пустые/whitespace/undefined → undefined (дефолт бэкенда)", () => {
    expect(scalar(undefined)).toBeUndefined();
    expect(scalar("")).toBeUndefined();
    expect(scalar("   ")).toBeUndefined();
  });

  it("непустое → trim; массив → первый элемент", () => {
    expect(scalar(" 2026-05-01 ")).toBe("2026-05-01");
    expect(scalar(["2026-05-01", "2026-06-01"])).toBe("2026-05-01");
  });
});

describe("loadReport", () => {
  it("200 с data → { report }", async () => {
    mockReport.mockResolvedValue({ data: { report: "volume", rows: [] } } as never);
    await expect(loadReport("volume", {})).resolves.toEqual({
      report: { report: "volume", rows: [] },
    });
  });

  it("200 без data → мягкая деградация в error", async () => {
    mockReport.mockResolvedValue({} as never);
    await expect(loadReport("sla", {})).resolves.toEqual({ error: "Отчёт недоступен" });
  });

  it("403 → { forbidden: true }", async () => {
    mockReport.mockImplementation(() => {
      throw new ApiError(403, "Forbidden");
    });
    await expect(loadReport("operators", {})).resolves.toEqual({ forbidden: true });
  });

  it("422 (битый период) → нейтральная error без утечки detail", async () => {
    mockReport.mockImplementation(() => {
      throw new ApiError(422, "Unprocessable Entity");
    });
    const result = await loadReport("volume", { from: "bad" });
    expect(result).toEqual({ error: "Не удалось загрузить отчёт" });
    expect(JSON.stringify(result)).not.toContain("Unprocessable");
  });
});
