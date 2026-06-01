import { describe, expect, it, vi } from "vitest";

// transport тянет next/headers (RSC) через server-token — мокаем; транспорт
// инжектируем в хелперы через deps.
vi.mock("@/lib/server-token", () => ({ getServerAccessToken: vi.fn() }));

import {
  ApiError,
  assignTicket,
  closeTicket,
  getTicket,
  getTicketHistory,
  listTickets,
  request,
  updateTicket,
} from "@/lib/api/client";

// API base из vitest.setup.ts (корень хоста); путь /api/v1 добавляют хелперы.
const BASE = "https://kb-support.local";

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const problem = (status: number, title: string, extra: Record<string, unknown> = {}): Response =>
  new Response(JSON.stringify({ type: "about:blank", title, status, ...extra }), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });

const okFetch = (response: Response) => vi.fn<typeof fetch>(() => Promise.resolve(response));
const deps = (response: Response) => ({
  getAccessToken: async () => "tok",
  fetchImpl: okFetch(response),
});

describe("typed client — success", () => {
  it("listTickets парсит конверт и шлёт Bearer + X-Request-Id на верный URL", async () => {
    const d = deps(json({ status: "ok", data: [{ id: "t1" }], pagination: {} }));
    const result = await listTickets({ status: "OPEN" }, d);

    expect(result.data?.[0]?.id).toBe("t1");
    const [url, init] = d.fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/support/tickets?status=OPEN`);
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
    expect(headers.get("X-Request-Id")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
  });

  it("updateTicket шлёт PATCH с телом", async () => {
    const d = deps(json({ status: "ok", data: { id: "t1" } }));
    await updateTicket("t1", { priority: "high" }, d);
    const [url, init] = d.fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/support/tickets/t1`);
    expect(init?.method).toBe("PATCH");
    expect(init?.body).toBe(JSON.stringify({ priority: "high" }));
  });

  it("assignTicket шлёт POST с assignee_id", async () => {
    const d = deps(json({ data: { id: "t1" } }));
    await assignTicket("t1", { assignee_id: "u9" }, d);
    const [url, init] = d.fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/support/tickets/t1/assign`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ assignee_id: "u9" }));
  });

  it("closeTicket шлёт POST без тела", async () => {
    const d = deps(json({ data: { id: "t1" } }));
    await closeTicket("t1", d);
    const [url, init] = d.fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/support/tickets/t1/close`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
  });

  it("getTicketHistory шлёт GET на /history и парсит конверт", async () => {
    const d = deps(json({ data: [{ id: "h1", action: "created" }], request_id: "r1" }));
    const result = await getTicketHistory("t1", d);

    expect(result.data?.[0]?.action).toBe("created");
    const [url, init] = d.fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/support/tickets/t1/history`);
    expect(init?.method).toBe("GET");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok");
  });
});

describe("typed client — ошибки RFC7807", () => {
  it("401 → ApiError со статусом 401", async () => {
    const d = deps(problem(401, "Unauthorized"));
    await expect(getTicket("t1", d)).rejects.toMatchObject({ status: 401 });
  });

  it("404 → ApiError со статусом 404", async () => {
    const d = deps(problem(404, "Not Found"));
    await expect(getTicket("t1", d)).rejects.toBeInstanceOf(ApiError);
    await expect(getTicket("t1", deps(problem(404, "Not Found")))).rejects.toMatchObject({
      status: 404,
    });
  });

  it("422 → ApiError со статусом 422 и доступным problem.errors", async () => {
    const d = deps(
      problem(422, "Validation failed", { errors: [{ field: "type", message: "bad" }] }),
    );
    try {
      await getTicket("t1", d);
      throw new Error("должно было бросить");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(422);
      expect(apiErr.problem?.errors?.[0]?.field).toBe("type");
    }
  });

  it("не-problem+json ошибка → ApiError без падения парсинга", async () => {
    const d = {
      getAccessToken: async () => "tok",
      fetchImpl: vi.fn<typeof fetch>(() => Promise.resolve(new Response("oops", { status: 500 }))),
    };
    await expect(getTicket("t1", d)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("typed client — ФЗ-152: detail (ПДн) не утекает в логируемые поля", () => {
  const PII = "ivan@example.com";

  it("detail не попадает ни в message, ни в JSON.stringify(error), но доступен через problem", async () => {
    const d = deps(problem(422, "Validation failed", { detail: `нарушитель ${PII}` }));
    let caught: ApiError | undefined;
    try {
      await getTicket("t1", d);
    } catch (err) {
      caught = err as ApiError;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.message).toBe("422 Validation failed");
    expect(caught?.message).not.toContain(PII);
    // problem хранится в WeakMap, не на instance — JSON-лог не выгрузит ПДн.
    expect(JSON.stringify(caught)).not.toContain(PII);
    // но программно detail доступен для UI.
    expect(caught?.problem?.detail).toContain(PII);
  });
});

describe("X-Request-Id", () => {
  it("переопределяется вызывающим через request()", async () => {
    const d = deps(json({ status: "ok" }));
    await request("/api/v1/support/stats", "GET", { requestId: "fixed-req-id", deps: d });
    const [, init] = d.fetchImpl.mock.calls[0];
    expect(new Headers(init?.headers).get("X-Request-Id")).toBe("fixed-req-id");
  });
});
