import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

import { PeriodSelector } from "./PeriodSelector";

describe("PeriodSelector", () => {
  beforeEach(() => push.mockClear());

  it("пустые поля → переход на /dashboard БЕЗ query (сработает дефолт бэкенда)", () => {
    render(<PeriodSelector />);
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));
    expect(push).toHaveBeenCalledWith("/dashboard");
  });

  it("заполненный период → query from/to в URL", () => {
    render(<PeriodSelector from="2026-05-01" to="2026-05-31" />);
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));
    expect(push).toHaveBeenCalledWith("/dashboard?from=2026-05-01&to=2026-05-31");
  });

  it("«Сбросить» очищает период (переход на /dashboard)", () => {
    render(<PeriodSelector from="2026-05-01" to="2026-05-31" />);
    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(push).toHaveBeenCalledWith("/dashboard");
  });
});
