import { describe, expect, it } from "vitest";

import { parseQuery, queryKey, toSearchString, updateField } from "./query";

describe("parseQuery", () => {
  it("пустые searchParams → пустой запрос", () => {
    expect(parseQuery({})).toEqual({});
  });

  it("разбирает строковые фильтры и sort", () => {
    expect(parseQuery({ status: "OPEN", team: "legal", tag: "vip", sort: "-created_at" })).toEqual({
      status: "OPEN",
      team: "legal",
      tag: "vip",
      sort: "-created_at",
    });
  });

  it("игнорирует невалидный sort", () => {
    expect(parseQuery({ sort: "bogus" })).toEqual({});
  });

  it("приводит sla_breached к boolean, игнорирует мусор", () => {
    expect(parseQuery({ sla_breached: "true" })).toEqual({ sla_breached: true });
    expect(parseQuery({ sla_breached: "false" })).toEqual({ sla_breached: false });
    expect(parseQuery({ sla_breached: "maybe" })).toEqual({});
  });

  it("берёт первый элемент при массиве значений", () => {
    expect(parseQuery({ status: ["OPEN", "NEW"] })).toEqual({ status: "OPEN" });
  });
});

describe("toSearchString", () => {
  it("сериализует и отбрасывает пустые", () => {
    const qs = toSearchString({ status: "OPEN", sla_breached: true, tag: "" });
    const params = new URLSearchParams(qs);
    expect(params.get("status")).toBe("OPEN");
    expect(params.get("sla_breached")).toBe("true");
    expect(params.has("tag")).toBe(false);
  });
});

describe("queryKey", () => {
  it("стабилен независимо от порядка ключей", () => {
    expect(queryKey({ status: "OPEN", team: "legal" })).toBe(
      queryKey({ team: "legal", status: "OPEN" }),
    );
  });

  it("не зависит от cursor/limit (пагинация, не фильтр)", () => {
    expect(queryKey({ status: "OPEN", cursor: "c1", limit: 20 })).toBe(
      queryKey({ status: "OPEN" }),
    );
  });
});

describe("updateField", () => {
  it("устанавливает значение и сбрасывает cursor", () => {
    expect(updateField({ cursor: "c1" }, "status", "OPEN")).toEqual({ status: "OPEN" });
  });

  it("пустая строка удаляет поле", () => {
    expect(updateField({ status: "OPEN" }, "status", "")).toEqual({});
  });

  it("sla_breached приводится к boolean", () => {
    expect(updateField({}, "sla_breached", "true")).toEqual({ sla_breached: true });
    expect(updateField({}, "sla_breached", "false")).toEqual({ sla_breached: false });
  });
});
