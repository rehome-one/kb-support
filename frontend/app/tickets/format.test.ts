import { describe, expect, it } from "vitest";

import { STATUS_LABELS, formatDateTime, label, shortId } from "./format";

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
