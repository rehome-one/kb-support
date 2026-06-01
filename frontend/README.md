# kb-support frontend — рабочее место оператора (E2)

Next.js 14 (App Router) + React 18 + TypeScript strict + Tailwind. Подключается в
kb-staff кабинет как отдельный раздел; связь с kb-support — только по HTTP API
(`docs/openapi.yaml`), аутентификация — Keycloak OIDC → Bearer (бэкенд #29).

## Команды

```bash
npm ci            # установка (как в CI)
npm run dev       # dev-сервер (localhost:3000)
npm run lint      # next lint + prettier --check
npm run typecheck # tsc --noEmit (strict)
npm test          # vitest (watch); CI: npm test -- --run
npm run build     # production build (standalone)
npm run format    # prettier --write
```

## Структура

- `app/` — App Router (layout, page, login, route handler Auth.js).
- `auth.ts` / `auth.config.ts` — конфигурация Auth.js (полная / edge для middleware).
- `middleware.ts` — guard защищённых маршрутов.
- `lib/` — env-валидация, логика токенов Keycloak, серверный API-клиент.
- `vitest.config.ts` / `vitest.setup.ts` — Vitest + Testing Library (jsdom).
- `Dockerfile` — multi-stage standalone build.

## SSO (E2-2, #43)

Вход через Keycloak (OIDC authorization code flow + PKCE) на базе **Auth.js v5**.
Сессия — JWT в httpOnly cookie; access/refresh токены живут только на сервере и
**не отдаются в браузер**. Серверный транспорт `lib/api/transport.ts` прокидывает
access token как `Bearer` в API kb-support.

Переменные окружения — см. `.env.example` (скопировать в `.env.local`). Реальные
значения Keycloak — у ops/kb-auth.

> **Зависимость (ops/kb-auth):** access token client'а фронта должен содержать
> `aud: kb-support`, иначе бэкенд (#29, `verify_aud`) отклонит запрос — нужен
> audience-mapper на client'е `kb-support-frontend` в Keycloak.

## API-клиент (E2-3, #44)

Типобезопасный клиент к kb-support — единственная публичная поверхность `lib/api`:

- `lib/api/schema.d.ts` — **сгенерированные** типы из контракта `docs/openapi.yaml`
  (`openapi-typescript`). Машинный артефакт, коммитится.
- `lib/api/client.ts` — типизированные хелперы (`listTickets`/`getTicket`/
  `updateTicket`/`listMessages`/`createMessage` + actions), `ApiError` (RFC7807),
  генерация `X-Request-Id`.
- `lib/api/transport.ts` — низкоуровневый транспорт (Bearer/server-only) из #43.

```bash
npm run gen:api        # регенерировать типы из ../docs/openapi.yaml
npm run gen:api:check  # проверка drift (CI: типы ↔ контракт)
```

> `ApiError.message` = `<status> <title>` (без `detail` — потенциальные ПДн);
> полный problem доступен через `error.problem`, но не сериализуется в логи.

Экраны (список/карточка/переписка/действия) — задачи #45–#49.

## Архитектурная константа

Отдельная кодовая база. Никаких импортов из rehome-kb-platform; данные — только
через API kb-support.
