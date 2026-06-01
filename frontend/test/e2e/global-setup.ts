/**
 * Mock-login для E2E-smoke (#49): без реального Keycloak-round-trip (это #52,
 * ждёт ops-провижининга realm). Куём валидную session-cookie тем же encode из
 * `@auth/core/jwt`, что использует приложение под капотом, и сохраняем
 * storageState — тесты стартуют уже аутентифицированными.
 *
 * Прод-auth НЕ модифицируется (никаких test-only веток в auth.ts): подмена идёт
 * строго снаружи, через cookie, которую сервер расшифрует штатным getToken.
 *
 * Тонкость: два прод-пути расходятся в имени cookie в этом окружении.
 *  - middleware (NextAuth core) выводит useSecureCookies из протокола запроса:
 *    http://localhost → false → имя `authjs.session-token`;
 *  - `getServerAccessToken` жёстко передаёт secureCookie=NODE_ENV==='production'
 *    (под `next start` = true) → имя `__Secure-authjs.session-token`.
 * Поэтому кладём ОБЕ cookie, каждую с salt = её собственное имя (salt в Auth.js
 * v5 = имя cookie). Прод-код не трогаем — подмена строго снаружи.
 *
 * Прочие инварианты, без которых smoke краснеет (см. ревью плана):
 *  - `access_token` в токене — иначе apiFetch бросит UnauthenticatedError;
 *  - `name`/`email`/`sub` — иначе middleware (isAuthorized: auth.user) редиректит;
 *  - `expires_at` в будущем — иначе jwt-callback дёрнул бы реальный Keycloak.
 */

import fs from "node:fs";
import path from "node:path";

import { encode } from "@auth/core/jwt";

import {
  APP_URL,
  AUTH_SECRET,
  SESSION_COOKIE,
  SESSION_COOKIE_INSECURE,
  STORAGE_STATE,
} from "./constants";

const ONE_HOUR = 60 * 60;

export default async function globalSetup(): Promise<void> {
  const nowSec = Math.floor(Date.now() / 1000);
  const expires = nowSec + ONE_HOUR;

  const token = {
    name: "E2E Оператор",
    email: "operator@e2e.local",
    sub: "33333333-3333-4333-8333-333333333333",
    access_token: "e2e-access-token",
    refresh_token: "e2e-refresh-token",
    expires_at: expires,
  };

  const { hostname } = new URL(APP_URL);

  // salt = имя cookie (инвариант encode/decode Auth.js v5).
  const mint = async (name: string, secure: boolean) => ({
    name,
    value: await encode({ token, secret: AUTH_SECRET, salt: name, maxAge: ONE_HOUR }),
    domain: hostname,
    path: "/",
    httpOnly: true,
    // localhost — secure context: Chromium принимает Secure-cookie и по http.
    secure,
    sameSite: "Lax" as const,
    expires,
  });

  const storageState = {
    cookies: [
      await mint(SESSION_COOKIE_INSECURE, false), // читает middleware (http)
      await mint(SESSION_COOKIE, true), // читает getServerAccessToken (prod)
    ],
    origins: [],
  };

  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
  fs.writeFileSync(STORAGE_STATE, JSON.stringify(storageState, null, 2));
}
