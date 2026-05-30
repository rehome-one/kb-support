# kb-support

> Модуль службы поддержки платформы reHome — приём, обработка и сопровождение
> обращений пользователей силами операторов.

## Статус

🟢 **Phase 0 / Bootstrap** (2026-05-30) — репозиторий создан, handoff-пакет
готов, разработка кода ещё не начата. Первая задача — Issue #1 / E1 «Ядро
заявок» (Ticket, TicketMessage, статусы, CRUD API, история).

## Что это

Helpdesk-модуль уровня Okdesk-ядра, адаптированный под аренду жилья reHome.
Принимает обращения от заявителей (нанимателей, собственников, агентов) по
нескольким каналам (AI-чат kb-search — главный, email, веб-форма, телефон),
маршрутизирует операторам по командам (support / legal / finance) и
сопровождает до решения с контролем SLA. v1.1 добавляет претензионные типы
(COMPENSATION / GUARANTEE / INSURANCE / ACCEPTANCE_ACT) с собственной
процедурой разбирательства по Договору найма.

Реализовано по принципу ADR-0001 «разрабатываем сами, минимум внешних
сервисов».

## Архитектурная константа

**kb-support — отдельный, независимо развёртываемый сервис.**

- Свой репозиторий (`rehome-one/kb-support`).
- Своя БД (PostgreSQL, отдельный кластер от kb-platform).
- Свой деплой (отдельный pipeline).
- Связь с базой знаний (`rehome-kb-platform`) и с основной платформой
  rehome.one — **только по сети, по API**.
- Никаких shared таблиц. Никакого shared кода.

Эта константа повторяется в §1.4, NFR-4.4, ADR-0005 ТЗ.

## Связь с другими модулями reHome

| Модуль | Что используем | Как |
|---|---|---|
| `kb-search` | Эскалация AI-чата → создание заявки | API `POST /chat/sessions/{id}/escalate` (входящий webhook) |
| `kb-auth` | Аутентификация операторов, scope | Keycloak SSO |
| `kb-wiki` / `kb-help` | Предложение статей в шаблонах | read-only через API kb-platform |
| `kb-files` | Хранилище вложений | API (своё подкаталог MinIO, не shared bucket) |
| rehome.one platform | User / Premises / Booking / Collaborator / ServiceOrder | HTTP-клиент с Redis-кешем |
| Платёжный контур (E10) | Выплата по решению | `BankProvider.releasePayout` (внешний API) |

Все интеграции — slabaja связанность, graceful degradation: сбой соседа
не валит kb-support.

## Технологический стек

**Backend:**
- Python 3.12+ / FastAPI
- PostgreSQL 16+
- Redis (кеш external API, очереди Dramatiq)
- Dramatiq (SLA-таймеры, IMAP-парсер email, time-based AutomationRule)
- MinIO (через kb-files API)
- Keycloak (через kb-auth API)

**Frontend:**
- Next.js 14+ (App Router) — рабочее место оператора, подключается в
  kb-staff кабинет как отдельный раздел через SSO
- React 18+ / TypeScript strict / Tailwind CSS

**Тестирование:**
- Backend: pytest, pytest-asyncio, pytest-cov, contract tests via Prism mock
- Frontend: Vitest, Playwright (E2E)

## Структура репозитория (по мере развития)

```
.
├── CLAUDE.md                            ← операционная инструкция Разработчика
├── CLAUDE-REVIEWER.md                   ← операционная инструкция Проверяющего
├── README.md                            ← этот файл
├── .github/                             ← CI, PR/Issue templates
├── docs/
│   ├── architecture.md                  ← обзор архитектуры (заполняется на E1)
│   ├── state-of-code.md                 ← живой baseline артефакт
│   ├── adr/                             ← Architecture Decision Records
│   │   ├── 0000-template.md
│   │   ├── 0001-platform-architecture.md     ← наследуется из kb-platform
│   │   ├── 0003-knowledge-base-tiers.md      ← наследуется из kb-platform
│   │   ├── 0004-collaborators-model.md       ← наследуется из kb-platform
│   │   └── 0005-support-module.md            ← главное решение по kb-support
│   ├── handoff/
│   │   ├── HANDOFF.md
│   │   ├── INDEX.md
│   │   ├── 01_postanovka/
│   │   │   ├── 01_TZ_kb_support_v2.2.md          ← главное ТЗ
│   │   │   └── 04_openapi.yaml                   ← OpenAPI 3.1 v1.1 контракт
│   │   └── 02_process/                            ← (заполняется по ходу)
│   └── runbooks/                         ← (заполняется по ходу)
├── backend/                              ← (создаётся на E1)
│   ├── src/api/
│   ├── tests/
│   └── pyproject.toml
└── frontend/                             ← (создаётся на E2)
    ├── app/
    ├── lib/
    └── package.json
```

## Двухагентная схема

- **Developer agent (Claude Code)** — пишет код по утверждённому плану.
  Правила в `CLAUDE.md`.
- **Reviewer agent (отдельная Claude Code сессия)** — ревьюит PR.
  Правила в `CLAUDE-REVIEWER.md`.
- **Архитектор (Evgeniy)** — резолвит споры, принимает ADR, утверждает
  отступления от правил ТЗ.

## Этапы реализации (план)

| Этап | Объём | Срок (ориентир) |
|---|---|---|
| E1 | Ядро заявок | 2 нед |
| E2 | Рабочее место оператора | 2 нед |
| E3 | Интеграция с AI-чатом kb-search | 2 нед |
| E4 | SLA | 1.5 нед |
| E5 | Автоматизация | 1.5 нед |
| E6 | Шаблоны и база знаний | 1 нед |
| E7 | Каналы email/форма | 2 нед |
| E8 | Аналитика | 1.5 нед |
| E9 | Оценка качества | 0.5 нед |
| E10 | Претензионные типы | 2-3 нед |

Итого ~16-17 недель.

## Команды для разработки

```bash
# Backend (внутри backend/)
ruff check . && ruff format --check .
mypy --strict
pytest --cov=. --cov-fail-under=80

# Frontend (внутри frontend/)
npm install
npm run lint
npm run typecheck
npm run test

# OpenAPI lint
npx @redocly/cli lint docs/handoff/01_postanovka/04_openapi.yaml

# Mock-сервер для разработки фронтенда
npx @stoplight/prism-cli mock docs/handoff/01_postanovka/04_openapi.yaml --port 8080
```

## Контакты

| Роль | Кто |
|---|---|
| Архитектор проекта | Evgeniy |
| Канал эскалаций | Чат Claude Code |

## Связанные документы

- [docs/handoff/HANDOFF.md](docs/handoff/HANDOFF.md) — точка входа в передаточный пакет
- [docs/handoff/01_postanovka/01_TZ_kb_support_v2.2.md](docs/handoff/01_postanovka/01_TZ_kb_support_v2.2.md) — главное ТЗ
- [docs/adr/0005-support-module.md](docs/adr/0005-support-module.md) — ADR-0005 (5 принятых решений)
- [CLAUDE.md](CLAUDE.md) — операционная инструкция Разработчика
- [CLAUDE-REVIEWER.md](CLAUDE-REVIEWER.md) — операционная инструкция Проверяющего
