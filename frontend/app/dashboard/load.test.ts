import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, getSupportStats: vi.fn() };
});

import { ApiError, getSupportStats } from "@/lib/api/client";

import { loadStats, scalar } from "./load";

const mockStats = vi.mocked(getSupportStats);

describe("scalar", () => {
  it("пустые/whitespace/undefined → undefined (сработает дефолт бэкенда)", () => {
    expect(scalar(undefined)).toBeUndefined();
    expect(scalar("")).toBeUndefined();
    expect(scalar("   ")).toBeUndefined();
  });

  it("непустое значение → trim; массив → первый элемент", () => {
    expect(scalar(" 2026-05-01 ")).toBe("2026-05-01");
    expect(scalar(["2026-05-01", "2026-06-01"])).toBe("2026-05-01");
  });
});

describe("loadStats", () => {
  it("200 с data → { stats }", async () => {
    mockStats.mockResolvedValue({ data: { tickets: { total: 5 } } } as never);
    await expect(loadStats({})).resolves.toEqual({ stats: { tickets: { total: 5 } } });
  });

  it("200 без data → мягкая деградация в error", async () => {
    mockStats.mockResolvedValue({} as never);
    await expect(loadStats({})).resolves.toEqual({ error: "Статистика недоступна" });
  });

  it("403 → { forbidden: true }", async () => {
    mockStats.mockImplementation(() => {
      throw new ApiError(403, "Forbidden");
    });
    await expect(loadStats({})).resolves.toEqual({ forbidden: true });
  });

  it("422 (битый период) → нейтральная error-ветка, без утечки detail", async () => {
    mockStats.mockImplementation(() => {
      throw new ApiError(422, "Unprocessable Entity");
    });
    const result = await loadStats({ from: "bad" });
    expect(result).toEqual({ error: "Не удалось загрузить статистику" });
    // detail из problem наружу не выводится — только фиксированная строка
    expect(JSON.stringify(result)).not.toContain("Unprocessable");
  });
});
