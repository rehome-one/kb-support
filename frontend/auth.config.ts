/**
 * Edge-совместимая часть конфигурации Auth.js: только guard защищённых
 * маршрутов и страница входа. Без провайдеров и чтения секретов — этот конфиг
 * грузится в middleware (edge runtime). Полная конфигурация (Keycloak provider,
 * jwt/session callbacks) — в `auth.ts` (node runtime).
 */

import type { NextAuthConfig } from "next-auth";

import { isAuthorized } from "@/lib/auth-callbacks";

export const authConfig = {
  pages: { signIn: "/login" },
  providers: [],
  callbacks: {
    authorized({ auth }) {
      return isAuthorized(auth);
    },
  },
} satisfies NextAuthConfig;
