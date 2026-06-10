import { describe, expect, it } from "vitest";

import {
  ACT_KIND_LABELS,
  AUTHOR_TYPE_LABELS,
  CASE_STATE_LABELS,
  DECISION_LABELS,
  HISTORY_ACTION_LABELS,
  SIGNING_STATUS_LABELS,
  SLA_STATE_LABELS,
  STATUS_LABELS,
  formatDateTime,
  formatHistoryDiff,
  formatScalar,
  isClaimType,
  label,
  shortId,
  slaStateClass,
} from "./format";

describe("SLA-состояние", () => {
  it("лейблы покрывают все значения домена", () => {
    expect(SLA_STATE_LABELS).toMatchObject({
      none: "Нет SLA",
      ok: "OK",
      approaching: "Скоро дедлайн",
      breached: "Нарушен",
    });
  });

  it("цветовой класс по состоянию, нейтральный для неизвестного", () => {
    expect(slaStateClass("ok")).toBe("text-green-600");
    expect(slaStateClass("approaching")).toBe("text-amber-500");
    expect(slaStateClass("breached")).toBe("text-red-600");
    expect(slaStateClass("none")).toBe("text-gray-400");
    expect(slaStateClass(undefined)).toBe("text-gray-400");
    expect(slaStateClass("weird")).toBe("text-gray-400");
  });
});

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

describe("претензионные лейблы (E10, #201)", () => {
  it("CASE_STATE_LABELS покрывает все 8 состояний разбирательства", () => {
    expect(Object.keys(CASE_STATE_LABELS)).toHaveLength(8);
    expect(label(CASE_STATE_LABELS, "UNDER_REVIEW")).toBe("На рассмотрении");
    expect(label(CASE_STATE_LABELS, "PAID")).toBe("Выплачено");
  });

  it("DECISION_LABELS покрывает 3 вердикта", () => {
    expect(Object.keys(DECISION_LABELS)).toEqual(["FULL", "PARTIAL", "REJECTED"]);
    expect(label(DECISION_LABELS, "PARTIAL")).toBe("Частичное удовлетворение");
  });

  it("ACT_KIND_LABELS и SIGNING_STATUS_LABELS покрывают домен", () => {
    expect(label(ACT_KIND_LABELS, "MOVE_OUT")).toBe("Акт выселения");
    expect(label(SIGNING_STATUS_LABELS, "both_signed")).toBe("Подписан обеими сторонами");
  });

  it("label фолбэчит на «—» для null case_state", () => {
    expect(label(CASE_STATE_LABELS, null)).toBe("—");
  });
});

describe("isClaimType", () => {
  it("истинно для всех claims-типов", () => {
    for (const t of ["COMPENSATION", "GUARANTEE", "INSURANCE", "ACCEPTANCE_ACT"]) {
      expect(isClaimType(t)).toBe(true);
    }
  });

  it("ложно для обычных типов и пустого значения", () => {
    expect(isClaimType("PAYMENT")).toBe(false);
    expect(isClaimType(null)).toBe(false);
    expect(isClaimType(undefined)).toBe(false);
  });
});

describe("formatScalar (нейтральный рендер payload)", () => {
  it("примитивы → строка, объекты → JSON, null → ∅", () => {
    expect(formatScalar(42)).toBe("42");
    expect(formatScalar("x")).toBe("x");
    expect(formatScalar(null)).toBe("∅");
    expect(formatScalar({ a: 1 })).toBe('{"a":1}');
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
