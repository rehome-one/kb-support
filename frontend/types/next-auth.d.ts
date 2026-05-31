/**
 * Расширение типов Auth.js под токены Keycloak.
 *
 * `Session` (отдаётся клиенту) намеренно НЕ содержит access/refresh токенов —
 * только неконфиденциальные поля. Сами токены живут в `JWT` (серверный
 * httpOnly cookie).
 */

declare module "next-auth" {
  interface Session {
    expiresAt?: number;
    error?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    access_token?: string;
    refresh_token?: string;
    expires_at?: number;
    error?: string;
  }
}

export {};
