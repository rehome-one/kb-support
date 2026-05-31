import { describe, expect, it, vi } from "vitest";

import {
  isAccessTokenValid,
  REFRESH_ERROR,
  refreshAccessToken,
  type KeycloakClientConfig,
  type OidcTokenSet,
} from "@/lib/keycloak";

const CONFIG: KeycloakClientConfig = {
  issuer: "https://kc.local/realms/rehome",
  clientId: "kb-support-frontend",
  clientSecret: "secret",
};

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const fetchReturning = (response: Response) => vi.fn<typeof fetch>(() => Promise.resolve(response));

describe("isAccessTokenValid", () => {
  it("valid, когда now раньше expires_at", () => {
    expect(isAccessTokenValid({ expires_at: 2000 }, 1_000_000)).toBe(true);
  });

  it("invalid, когда access token истёк", () => {
    expect(isAccessTokenValid({ expires_at: 500 }, 1_000_000)).toBe(false);
  });

  it("invalid, когда expires_at отсутствует", () => {
    expect(isAccessTokenValid({}, 1_000_000)).toBe(false);
  });
});

describe("refreshAccessToken", () => {
  it("обновляет токен и вычисляет expires_at по инжектированному времени", async () => {
    const fetchImpl = fetchReturning(
      jsonResponse({ access_token: "new-access", expires_in: 300, refresh_token: "rot-refresh" }),
    );
    const token: OidcTokenSet = {
      access_token: "old",
      refresh_token: "old-refresh",
      expires_at: 1,
    };
    const result = await refreshAccessToken(token, CONFIG, {
      fetch: fetchImpl,
      now: () => 1_000_000,
    });

    expect(result.access_token).toBe("new-access");
    expect(result.refresh_token).toBe("rot-refresh");
    expect(result.expires_at).toBe(1_000 + 300); // floor(1_000_000 / 1000) + expires_in
    expect(result.error).toBeUndefined();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("сохраняет прежний refresh_token, если Keycloak не вернул новый", async () => {
    const fetchImpl = fetchReturning(jsonResponse({ access_token: "new", expires_in: 60 }));
    const token: OidcTokenSet = { refresh_token: "keep-me", expires_at: 1 };
    const result = await refreshAccessToken(token, CONFIG, { fetch: fetchImpl, now: () => 0 });
    expect(result.refresh_token).toBe("keep-me");
  });

  it("возвращает error при не-2xx ответе и сохраняет исходные токены", async () => {
    const fetchImpl = fetchReturning(jsonResponse({ error: "invalid_grant" }, 400));
    const token: OidcTokenSet = {
      access_token: "old",
      refresh_token: "old-refresh",
      expires_at: 1,
    };
    const result = await refreshAccessToken(token, CONFIG, { fetch: fetchImpl, now: () => 0 });
    expect(result.error).toBe(REFRESH_ERROR);
    expect(result.access_token).toBe("old");
  });

  it("не ходит в сеть и возвращает error без refresh_token", async () => {
    const fetchImpl = fetchReturning(jsonResponse({}, 200));
    const token: OidcTokenSet = { access_token: "old" };
    const result = await refreshAccessToken(token, CONFIG, { fetch: fetchImpl, now: () => 0 });
    expect(result.error).toBe(REFRESH_ERROR);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
