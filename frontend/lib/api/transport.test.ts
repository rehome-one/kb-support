import { describe, expect, it, vi } from "vitest";

// server-token тянет next/headers (RSC-контекст) — мокаем, поведение токена
// инжектируем через deps.getAccessToken.
vi.mock("@/lib/server-token", () => ({ getServerAccessToken: vi.fn() }));

import { apiFetch, UnauthenticatedError } from "@/lib/api/transport";

// API base из vitest.setup.ts: https://kb-support.local/api/v1
const BASE = "https://kb-support.local/api/v1";

const fetchSpy = () =>
  vi.fn<typeof fetch>(() => Promise.resolve(new Response("[]", { status: 200 })));

describe("apiFetch", () => {
  it("проставляет Authorization: Bearer и бьёт по base URL из конфига", async () => {
    const fetchImpl = fetchSpy();
    await apiFetch(
      "/tickets",
      { method: "GET" },
      { getAccessToken: async () => "access-tok", fetchImpl },
    );

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/tickets`);
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-tok");
    expect(init?.method).toBe("GET");
  });

  it("сохраняет метод и заголовки вызывающего", async () => {
    const fetchImpl = fetchSpy();
    await apiFetch(
      "/tickets",
      { method: "POST", headers: { "Content-Type": "application/json" } },
      { getAccessToken: async () => "tok", fetchImpl },
    );
    const [, init] = fetchImpl.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(init?.method).toBe("POST");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer tok");
  });

  it("бросает UnauthenticatedError и не ходит в сеть без токена", async () => {
    const fetchImpl = fetchSpy();
    await expect(
      apiFetch("/tickets", {}, { getAccessToken: async () => undefined, fetchImpl }),
    ).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
