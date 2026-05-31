/**
 * Чистая логика работы с токенами Keycloak: проверка валидности access token и
 * обновление по refresh_token. Без зависимостей от next-auth — чтобы покрывать
 * unit-тестами без поднятия фреймворка. Сетевые вызовы и время инжектируются
 * (`RefreshDeps`), что делает функцию детерминированной в тестах.
 */

export interface OidcTokenSet {
  access_token?: string;
  refresh_token?: string;
  /** Время истечения access token, epoch-секунды. */
  expires_at?: number;
  /** Маркер неудачного refresh — потребляется UI для повторного входа. */
  error?: string;
}

export interface KeycloakClientConfig {
  issuer: string;
  clientId: string;
  clientSecret: string;
}

export interface RefreshDeps {
  fetch: typeof fetch;
  /** Текущее время, epoch-миллисекунды. */
  now: () => number;
}

export const REFRESH_ERROR = "RefreshAccessTokenError";

export function isAccessTokenValid(token: OidcTokenSet, nowMs: number): boolean {
  return typeof token.expires_at === "number" && nowMs < token.expires_at * 1000;
}

/**
 * Обновляет access token по refresh_token через token-endpoint Keycloak.
 * Generic `T` сохраняет тип входного токена (в проде это JWT next-auth).
 * При любой ошибке возвращает токен с выставленным `error`, не бросая
 * исключение, — чтобы сессия деградировала предсказуемо, а не падала.
 */
export async function refreshAccessToken<T extends OidcTokenSet>(
  token: T,
  config: KeycloakClientConfig,
  deps: RefreshDeps,
): Promise<T> {
  if (!token.refresh_token) {
    return { ...token, error: REFRESH_ERROR };
  }

  try {
    const response = await deps.fetch(`${config.issuer}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: config.clientId,
        client_secret: config.clientSecret,
        refresh_token: token.refresh_token,
      }),
    });

    if (!response.ok) {
      throw new Error(`token refresh failed: ${response.status}`);
    }

    const tokens = (await response.json()) as {
      access_token: string;
      expires_in: number;
      refresh_token?: string;
    };

    return {
      ...token,
      access_token: tokens.access_token,
      expires_at: Math.floor(deps.now() / 1000) + tokens.expires_in,
      // Keycloak ротирует refresh_token; если новый не пришёл — оставляем прежний.
      refresh_token: tokens.refresh_token ?? token.refresh_token,
      error: undefined,
    };
  } catch {
    return { ...token, error: REFRESH_ERROR };
  }
}
