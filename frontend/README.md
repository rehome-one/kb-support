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

## Структура (E2-1)

- `app/` — App Router (layout, page, components).
- `vitest.config.ts` / `vitest.setup.ts` — Vitest + Testing Library (jsdom).
- `Dockerfile` — multi-stage standalone build.

Экраны (список/карточка/переписка/действия) и SSO — задачи #43–#49.

## Архитектурная константа

Отдельная кодовая база. Никаких импортов из rehome-kb-platform; данные — только
через API kb-support.
