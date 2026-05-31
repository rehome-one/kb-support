import { describe, expect, it } from "vitest";

import { readEnv } from "@/lib/env";

const FULL = {
  AUTH_SECRET: "s",
  AUTH_KEYCLOAK_ID: "kb-support-frontend",
  AUTH_KEYCLOAK_SECRET: "cs",
  AUTH_KEYCLOAK_ISSUER: "https://kc.local/realms/rehome",
  KB_SUPPORT_API_BASE_URL: "https://api.local/v1/",
};

describe("readEnv", () => {
  it("разбирает все переменные и срезает завершающий слэш у API URL", () => {
    const env = readEnv(FULL);
    expect(env.keycloakId).toBe("kb-support-frontend");
    expect(env.apiBaseUrl).toBe("https://api.local/v1");
  });

  it("бросает с перечислением недостающих переменных", () => {
    const partial: Partial<typeof FULL> = { ...FULL };
    delete partial.AUTH_SECRET;
    delete partial.KB_SUPPORT_API_BASE_URL;
    expect(() => readEnv(partial)).toThrowError(/AUTH_SECRET.*KB_SUPPORT_API_BASE_URL/);
  });

  it("считает пустую строку отсутствующей переменной", () => {
    expect(() => readEnv({ ...FULL, AUTH_SECRET: "   " })).toThrowError(/AUTH_SECRET/);
  });
});
