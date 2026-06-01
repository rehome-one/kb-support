/**
 * Общие константы E2E-smoke (#49) — порты, URL, тестовый секрет, имя cookie и
 * путь к storageState. Импортируются playwright.config и global-setup.
 */

import path from "node:path";

export const APP_PORT = 3100;
export const FIXTURE_PORT = 3101;

export const APP_URL = `http://localhost:${APP_PORT}`;
export const FIXTURE_URL = `http://localhost:${FIXTURE_PORT}`;

/**
 * Тестовый секрет шифрования сессионного JWT. НЕ прод-значение — общий для
 * global-setup (encode cookie) и сервера приложения (decode через getToken),
 * иначе расшифровка молча провалится. Прод-секреты в репозиторий не коммитим.
 */
export const AUTH_SECRET = "e2e-insecure-test-secret-do-not-use-in-production-0001";

/**
 * Имя session-cookie в ПРОД-режиме (`next start` → NODE_ENV=production →
 * `getServerAccessToken` зовёт getToken с secureCookie=true). В Auth.js v5 при
 * secureCookie имя получает префикс `__Secure-`, и оно же служит salt для
 * encode/decode. Неверное имя → неверный salt → decode даёт null → 401.
 */
export const SESSION_COOKIE = "__Secure-authjs.session-token";

/**
 * Имя session-cookie без префикса — его ждёт middleware: NextAuth выводит
 * useSecureCookies из протокола запроса (http://localhost → false), а не из
 * NODE_ENV. Кладём обе cookie, чтобы оба прод-пути нашли свою.
 */
export const SESSION_COOKIE_INSECURE = "authjs.session-token";

/** Куда global-setup пишет аутентифицированный storageState. */
export const STORAGE_STATE = path.join(__dirname, ".auth", "operator.json");
