import { describe, expect, it } from "vitest";

import {
  AUTHOR_TYPE_LABELS,
  HISTORY_ACTION_LABELS,
  STATUS_LABELS,
  formatDateTime,
  formatHistoryDiff,
  label,
  shortId,
} from "./format";

describe("label", () => {
  it("возвращает лейбл по карте", () => {
    expect(label(STATUS_LABELS, "OPEN")).toBe("В работе");
  });

  it("откатывается к самому значению, если лейбла нет", () => {
    expect(label(STATUS_LABELS, "UNKNOWN")).toBe("UNKNOWN");
  });

  it("«—» для пустого", () => {
    expect(label(STATUS_LABELS, null)).toBe("—");
    expect(label(STATUS_LABELS, undefined)).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("форматирует ISO в дд.мм.гггг, чч:мм (МСК)", () => {
    // 09:30Z + МСК(+3) = 12:30
    const out = formatDateTime("2026-06-01T09:30:00Z");
    expect(out).toMatch(/01\.06\.2026/);
    expect(out).toMatch(/12:30/);
  });

  it("невалидную дату возвращает как есть, пустую — «—»", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
    expect(formatDateTime(null)).toBe("—");
  });
});

describe("shortId", () => {
  it("обрезает uuid до 8 символов", () => {
    expect(shortId("123e4567-e89b-12d3-a456-426614174000")).toBe("123e4567");
  });

  it("«—» для пустого", () => {
    expect(shortId(null)).toBe("—");
  });
});

describe("доменные лейблы карточки", () => {
  it("AUTHOR_TYPE_LABELS покрывает все значения AuthorType", () => {
    expect(label(AUTHOR_TYPE_LABELS, "ai")).toBe("AI-ассистент");
    expect(label(AUTHOR_TYPE_LABELS, "requester")).toBe("Заявитель");
  });

  it("HISTORY_ACTION_LABELS содержит 9 действий контракта", () => {
    expect(Object.keys(HISTORY_ACTION_LABELS)).toHaveLength(9);
    expect(label(HISTORY_ACTION_LABELS, "status_changed")).toBe("Смена статуса");
  });
});

describe("formatHistoryDiff", () => {
  it("created (from=null) → «→ …»", () => {
    expect(formatHistoryDiff(null, { status: "NEW" })).toBe("→ status: NEW");
  });

  it("status_changed → «from → to»", () => {
    expect(formatHistoryDiff({ status: "NEW" }, { status: "OPEN" })).toBe(
      "status: NEW → status: OPEN",
    );
  });

  it("message_added (служебный объект) форматируется без падения", () => {
    expect(formatHistoryDiff(null, { message_id: "m1", is_internal: false })).toBe(
      "→ message_id: m1, is_internal: false",
    );
  });

  it("оба пустые → пустая строка", () => {
    expect(formatHistoryDiff(null, null)).toBe("");
  });
});
