import "server-only";

import { readEnv } from "@/lib/env";
import { getServerAccessToken } from "@/lib/server-token";

/** Бросается, когда серверный вызов API делается без аутентифицированной сессии. */
export class UnauthenticatedError extends Error {
  constructor(message = "Нет access token в сессии") {
    super(message);
    this.name = "UnauthenticatedError";
  }
}

export interface ApiFetchDeps {
  /** Источник access token (по умолчанию — серверный JWT). Инъекция для тестов. */
  getAccessToken?: () => Promise<string | undefined>;
  fetchImpl?: typeof fetch;
}

/**
 * Серверный HTTP-клиент к API kb-support. Берёт access token из серверной сессии
 * и проставляет `Authorization: Bearer`. Токен в браузер не отдаётся — клиент
 * вызывается только на сервере (Server Components / Route Handlers).
 *
 * Базовый URL — из конфига (`KB_SUPPORT_API_BASE_URL`), не хардкод.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
  deps: ApiFetchDeps = {},
): Promise<Response> {
  const getAccessToken = deps.getAccessToken ?? getServerAccessToken;
  const fetchImpl = deps.fetchImpl ?? fetch;

  const accessToken = await getAccessToken();
  if (!accessToken) {
    throw new UnauthenticatedError();
  }

  const { apiBaseUrl } = readEnv();
  const requestHeaders = new Headers(init.headers);
  requestHeaders.set("Authorization", `Bearer ${accessToken}`);

  return fetchImpl(`${apiBaseUrl}${path}`, { ...init, headers: requestHeaders });
}
