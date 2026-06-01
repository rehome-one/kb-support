import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageThread } from "./MessageThread";
import type { TicketMessage } from "./types";

const msg = (over: Partial<TicketMessage> = {}): TicketMessage => ({
  id: "m1",
  ticket_id: "t1",
  author_id: "u1",
  author_type: "operator",
  body: "Текст сообщения",
  is_internal: false,
  attachments: [],
  created_at: "2026-06-01T09:30:00Z",
  ...over,
});

describe("MessageThread", () => {
  it("рендерит сообщения с лейблом автора и телом", () => {
    render(<MessageThread messages={[msg({ body: "Здравствуйте" })]} />);
    expect(screen.getByText("Оператор")).toBeInTheDocument();
    expect(screen.getByText("Здравствуйте")).toBeInTheDocument();
  });

  it("внутренняя заметка визуально выделена и помечена", () => {
    render(
      <MessageThread
        messages={[
          msg({ id: "m1", body: "ответ заявителю", is_internal: false }),
          msg({ id: "m2", body: "заметка для коллег", is_internal: true }),
        ]}
      />,
    );
    const internal = screen.getByText("заметка для коллег").closest("li");
    const normal = screen.getByText("ответ заявителю").closest("li");
    expect(internal).toHaveAttribute("data-internal", "true");
    expect(normal).toHaveAttribute("data-internal", "false");
    expect(within(internal as HTMLElement).getByText("Внутренняя заметка")).toBeInTheDocument();
  });

  it("лейбл автора берётся из author_type даже при author_id=null (ai)", () => {
    render(<MessageThread messages={[msg({ author_id: null, author_type: "ai" })]} />);
    expect(screen.getByText("AI-ассистент")).toBeInTheDocument();
  });

  it("пустой тред → сообщение-заглушка", () => {
    render(<MessageThread messages={[]} />);
    expect(screen.getByText("Сообщений пока нет.")).toBeInTheDocument();
  });
});
