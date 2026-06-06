import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageComposer } from "./MessageComposer";
import type { ActionResult, CannedSummary, RenderResult } from "./types";

const okAction = () => vi.fn().mockResolvedValue({ ok: true } satisfies ActionResult);
const noTemplates: CannedSummary[] = [];
const noRender = () =>
  vi.fn<(t: string, c: string) => Promise<RenderResult>>().mockResolvedValue({
    ok: true,
    body: "",
    linkedArticleSlug: null,
  });

function renderComposer(
  action = okAction(),
  templates: CannedSummary[] = noTemplates,
  renderTemplateAction = noRender(),
) {
  render(
    <MessageComposer
      ticketId="t1"
      createMessageAction={action}
      templates={templates}
      renderTemplateAction={renderTemplateAction}
    />,
  );
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

describe("MessageComposer — шаблоны (#131)", () => {
  const templates: CannedSummary[] = [
    { id: "c1", title: "Возврат", body: "", type: null, usage_count: 0 } as CannedSummary,
  ];

  it("выбор шаблона рендерит его и вставляет текст; отправка несёт canned_response_id", async () => {
    const createAction = okAction();
    const renderAction = vi
      .fn<(t: string, c: string) => Promise<RenderResult>>()
      .mockResolvedValue({ ok: true, body: "Здравствуйте, Иван!", linkedArticleSlug: null });
    render(
      <MessageComposer
        ticketId="t1"
        createMessageAction={createAction}
        templates={templates}
        renderTemplateAction={renderAction}
      />,
    );

    fireEvent.change(screen.getByLabelText("Вставить шаблон ответа"), {
      target: { value: "c1" },
    });
    await waitFor(() =>
      expect(screen.getByLabelText("Текст сообщения")).toHaveValue("Здравствуйте, Иван!"),
    );
    expect(renderAction).toHaveBeenCalledWith("t1", "c1");

    fireEvent.click(screen.getByRole("button", { name: "Отправить ответ" }));
    await waitFor(() =>
      expect(createAction).toHaveBeenCalledWith("t1", {
        body: "Здравствуйте, Иван!",
        is_internal: false,
        canned_response_id: "c1",
      }),
    );
  });

  it("без шаблонов селектор не показывается", () => {
    renderComposer();
    expect(screen.queryByLabelText("Вставить шаблон ответа")).not.toBeInTheDocument();
  });

  it("ошибка рендера шаблона → inline-алерт", async () => {
    const renderAction = vi
      .fn<(t: string, c: string) => Promise<RenderResult>>()
      .mockResolvedValue({ ok: false, status: 404, title: "Шаблон не найден" });
    render(
      <MessageComposer
        ticketId="t1"
        createMessageAction={okAction()}
        templates={templates}
        renderTemplateAction={renderAction}
      />,
    );
    fireEvent.change(screen.getByLabelText("Вставить шаблон ответа"), {
      target: { value: "c1" },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Шаблон не найден");
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
