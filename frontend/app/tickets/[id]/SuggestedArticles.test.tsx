import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SuggestedArticles } from "./SuggestedArticles";

describe("SuggestedArticles (#131)", () => {
  it("рендерит статьи ссылками", () => {
    render(
      <SuggestedArticles
        result={{
          degraded: false,
          articles: [
            { slug: "help/a", title: "Статья A", url: "http://w/a" },
            { slug: "help/b", title: "Статья B", url: null },
          ],
        }}
      />,
    );
    const link = screen.getByRole("link", { name: "Статья A" });
    expect(link).toHaveAttribute("href", "http://w/a");
    // Без url — просто текст, не ссылка.
    expect(screen.queryByRole("link", { name: "Статья B" })).not.toBeInTheDocument();
    expect(screen.getByText("Статья B")).toBeInTheDocument();
  });

  it("degraded → нейтральное сообщение «недоступны»", () => {
    render(<SuggestedArticles result={{ degraded: true, articles: [] }} />);
    expect(screen.getByText(/недоступны/i)).toBeInTheDocument();
  });

  it("пустой список → «не найдено»", () => {
    render(<SuggestedArticles result={{ degraded: false, articles: [] }} />);
    expect(screen.getByText(/не найдено/i)).toBeInTheDocument();
  });

  it("ошибка → текст ошибки", () => {
    render(<SuggestedArticles result={{ error: "Не удалось загрузить" }} />);
    expect(screen.getByText("Не удалось загрузить")).toBeInTheDocument();
  });
});
