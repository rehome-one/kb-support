/**
 * Чистые функции для callback'ов Auth.js — вынесены из `auth.ts`, чтобы
 * покрывать unit-тестами без инициализации NextAuth.
 *
 * Ключевой инвариант безопасности (NFR, план #43): access/refresh токены живут
 * ТОЛЬКО в серверном (httpOnly, зашифрованном) JWT и НИКОГДА не попадают в
 * клиентскую сессию — см. `shapeClientSession`.
 */

import type { OidcTokenSet } from "@/lib/keycloak";

export interface AccountLike {
  access_token?: string;
  refresh_token?: string;
  expires_at?: number;
}

/** Первый вход: переносим токены провайдера в серверный JWT. */
export function applyAccountTokens<T extends OidcTokenSet>(token: T, account: AccountLike): T {
  return {
    ...token,
    access_token: account.access_token,
    refresh_token: account.refresh_token,
    expires_at: account.expires_at,
  };
}

export interface ClientSessionExtras {
  /** Истечение access token (epoch-секунды) — неконфиденциально, для UI. */
  expiresAt?: number;
  /** Маркер ошибки refresh — UI инициирует повторный вход. */
  error?: string;
}

/**
 * Формирует объект сессии, отдаваемый КЛИЕНТУ. Намеренно НЕ включает
 * access_token/refresh_token: они остаются только в серверном JWT. Это и есть
 * защита «токен не утекает в браузер» — покрыто security-тестом.
 */
export function shapeClientSession<S extends object>(
  session: S,
  token: OidcTokenSet,
): S & ClientSessionExtras {
  return {
    ...session,
    expiresAt: token.expires_at,
    error: token.error,
  };
}

/** Предикат guard'а: доступ только при наличии аутентифицированного пользователя. */
export function isAuthorized(auth: { user?: unknown } | null | undefined): boolean {
  return Boolean(auth?.user);
}
