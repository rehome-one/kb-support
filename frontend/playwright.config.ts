/**
 * Playwright-конфиг E2E-smoke рабочего места оператора (#49, E2-8).
 *
 * Поднимает два webServer'а: детерминированный мок-бэкенд (fixture-server.mjs) и
 * собранное приложение (`next start`, прод-режим — как реально деплоится). Вход
 * мокается через storageState из global-setup (см. mock-login там). Реальные
 * Keycloak/бэкенд в smoke не задействованы — это #52 (ждёт ops-провижининга).
 */

import { defineConfig, devices } from "@playwright/test";

import {
  APP_PORT,
  APP_URL,
  APP_READY_URL,
  AUTH_SECRET,
  FIXTURE_PORT,
  FIXTURE_URL,
  STORAGE_STATE,
} from "./test/e2e/constants";

// Окружение приложения: API → мок-фикстура, dummy-Keycloak (реальный IdP не
// вызывается, но env обязателен — lib/env.ts fail-fast).
const appEnv = {
  AUTH_SECRET,
  // Без trustHost Auth.js v5 в прод-режиме считает запрос недоверенным и
  // отдаёт «неаутентифицирован» → редирект на /login. AUTH_URL фиксирует
  // протокол (http → useSecureCookies=false для middleware).
  AUTH_TRUST_HOST: "true",
  AUTH_URL: APP_URL,
  AUTH_KEYCLOAK_ID: "kb-support-frontend",
  AUTH_KEYCLOAK_SECRET: "e2e-dummy-secret",
  AUTH_KEYCLOAK_ISSUER: "http://localhost:9/realms/e2e",
  KB_SUPPORT_API_BASE_URL: FIXTURE_URL,
};

export default defineConfig({
  testDir: "./test/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never" }]]
    : [["html", { open: "never" }]],
  globalSetup: "./test/e2e/global-setup.ts",

  use: {
    baseURL: APP_URL,
    storageState: STORAGE_STATE,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      command: "node test/e2e/fixture-server.mjs",
      env: { PORT: String(FIXTURE_PORT) },
      url: FIXTURE_URL,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
    },
    {
      command: `next start -p ${APP_PORT}`,
      env: appEnv,
      url: APP_READY_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
