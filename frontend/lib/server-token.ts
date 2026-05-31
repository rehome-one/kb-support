import "server-only";

import { headers } from "next/headers";
import { getToken } from "next-auth/jwt";

import { readEnv } from "@/lib/env";

/**
 * Достаёт access token из серверного JWT (httpOnly cookie). Помечен `server-only`
 * — никогда не попадает в клиентский бандл.
 *
 * Тонкая обвязка над `getToken` (cookie/секрет/имя cookie) проверяется на
 * интеграционном/E2E-уровне (#43-follow), т.к. требует реального cookie и
 * Keycloak. Unit-уровень покрывает поведение `apiFetch` через инъекцию
 * `getAccessToken`.
 */
export async function getServerAccessToken(): Promise<string | undefined> {
  const env = readEnv();
  const requestHeaders = headers();
  const token = await getToken({
    req: { headers: Object.fromEntries(requestHeaders.entries()) },
    secret: env.authSecret,
    secureCookie: process.env.NODE_ENV === "production",
  });
  return token?.access_token;
}
