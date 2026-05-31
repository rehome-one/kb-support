import { describe, expect, it } from "vitest";

import { applyAccountTokens, isAuthorized, shapeClientSession } from "@/lib/auth-callbacks";
import type { OidcTokenSet } from "@/lib/keycloak";

describe("applyAccountTokens", () => {
  it("переносит токены провайдера в JWT при первом входе, сохраняя прочие поля", () => {
    const existing: OidcTokenSet & { name?: string } = { name: "op" };
    const result = applyAccountTokens(existing, {
      access_token: "at",
      refresh_token: "rt",
      expires_at: 123,
    });
    expect(result).toMatchObject({
      name: "op",
      access_token: "at",
      refresh_token: "rt",
      expires_at: 123,
    });
  });
});

describe("shapeClientSession (инвариант: токен не утекает в браузер)", () => {
  const session = { user: { email: "op@rehome.local" }, expires: "2026-01-01" };
  const token = {
    access_token: "SECRET-ACCESS",
    refresh_token: "SECRET-REFRESH",
    expires_at: 1234,
    error: undefined,
  };

  it("НЕ включает access/refresh токены в клиентскую сессию", () => {
    const result = shapeClientSession(session, token);
    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("SECRET-ACCESS");
    expect(serialized).not.toContain("SECRET-REFRESH");
    expect("access_token" in result).toBe(false);
    expect("accessToken" in result).toBe(false);
    expect("refresh_token" in result).toBe(false);
  });

  it("пробрасывает неконфиденциальные поля (expiresAt, error) и сохраняет user", () => {
    const result = shapeClientSession(session, { ...token, error: "RefreshAccessTokenError" });
    expect(result.expiresAt).toBe(1234);
    expect(result.error).toBe("RefreshAccessTokenError");
    expect(result.user).toEqual({ email: "op@rehome.local" });
  });
});

describe("isAuthorized (guard)", () => {
  it("true при наличии пользователя", () => {
    expect(isAuthorized({ user: { email: "x" } })).toBe(true);
  });

  it("false без сессии или без пользователя", () => {
    expect(isAuthorized(null)).toBe(false);
    expect(isAuthorized(undefined)).toBe(false);
    expect(isAuthorized({})).toBe(false);
  });
});
