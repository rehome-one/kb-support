import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageComposer } from "./MessageComposer";
import type { ActionResult } from "./types";

const okAction = () => vi.fn().mockResolvedValue({ ok: true } satisfies ActionResult);

function renderComposer(action = okAction()) {
  render(<MessageComposer ticketId="t1" createMessageAction={action} />);
  return action;
}

const typeBody = (text: string) =>
  fireEvent.change(screen.getByLabelText("Текст сообщения"), { target: { value: text } });

describe("MessageComposer — отправка", () => {
  it("публичный ответ: is_internal=false, тело передано", async () => {
    const action = renderComposer();
    typeBody("Здравствуйте, решаем");
    fireEvent.click(screen.getByRole("button", { name: "Отправить ответ" }));
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith("t1", {
        body: "Здравствуйте, решаем",
        is_internal: false,
      }),
    );
  });

  it("security (NFR-1.3): при включённом тоггле шлётся is_internal=true", async () => {
    const action = renderComposer();
    typeBody("заметка для коллег");
    fireEvent.click(screen.getByRole("checkbox", { name: "Внутренняя заметка" }));
    fireEvent.click(screen.getByRole("button", { name: "Добавить заметку" }));
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith("t1", {
        body: "заметка для коллег",
        is_internal: true,
      }),
    );
  });

  it("тоггл internal показывает предупреждение «не видно заявителю»", () => {
    renderComposer();
    expect(screen.queryByText(/Не видно заявителю/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Внутренняя заметка" }));
    expect(screen.getByText(/Не видно заявителю/i)).toBeInTheDocument();
  });

  it("пустое тело блокирует отправку", () => {
    const action = renderComposer();
    expect(screen.getByRole("button", { name: "Отправить ответ" })).toBeDisabled();
    typeBody("   ");
    expect(screen.getByRole("button", { name: "Отправить ответ" })).toBeDisabled();
    expect(action).not.toHaveBeenCalled();
  });

  it("форма очищается по успеху", async () => {
    renderComposer();
    typeBody("текст");
    fireEvent.click(screen.getByRole("button", { name: "Отправить ответ" }));
    await waitFor(() => expect(screen.getByLabelText("Текст сообщения")).toHaveValue(""));
  });
});

describe("MessageComposer — ошибки", () => {
  it("403 → inline-алерт с текстом title", async () => {
    const action = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      title: "Только операторы могут добавлять внутренние заметки",
    } satisfies ActionResult);
    renderComposer(action);
    typeBody("x");
    fireEvent.click(screen.getByRole("button", { name: "Отправить ответ" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Только операторы могут добавлять внутренние заметки");
  });

  it("401 (истёкшая сессия) → алерт", async () => {
    const action = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      title: "Сессия истекла — войдите снова",
    } satisfies ActionResult);
    renderComposer(action);
    typeBody("x");
    fireEvent.click(screen.getByRole("button", { name: "Отправить ответ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Сессия истекла");
  });
});
