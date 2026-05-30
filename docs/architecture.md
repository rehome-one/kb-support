# Architecture overview — kb-support

> Phase 0 placeholder. Будет заполнен на E1 первой архитектурной итерацией.

## Текущее состояние

Модуль ещё не реализован. Целевая архитектура — в `handoff/01_postanovka/01_TZ_kb_support_v2.2.md`
(разделы 3 — модель данных, 4 — функциональные требования, 5 — НФТ).

## Целевые компоненты

- **backend/** — FastAPI сервис (Ticket, TicketMessage, TicketHistory, ...).
- **backend/worker/** — Dramatiq worker (SLA-таймеры, IMAP-парсер email,
  time-based AutomationRule).
- **backend/src/api/clients/** — HTTP-клиенты к external API (rehome.one platform,
  kb-search, kb-wiki, kb-files, kb-auth, BankProvider, Insurer webhook).
- **frontend/** — Next.js admin UI оператора.

## Архитектурная константа

См. `CLAUDE.md` раздел «Архитектурная константа».
kb-support — отдельный сервис. Никаких shared таблиц / shared кода с
rehome-kb-platform. Связь — только HTTP API.

### AT-001 — автоматическая проверка (CI)

Архитектурная константа enforce'ится через `scripts/check-arch-constraint.sh`
+ CI job `arch-constraint`. Скрипт грепит запрещённые паттерны:

- Python imports: `from (rehome_kb_platform|kb_platform|kb_search|kb_wiki|kb_vault|kb_files|kb_auth|kb_staff|kb_hr|kb_eval|kb_infra)`.
- TypeScript imports: то же с dash-separated именами в кавычках.
- SQL: `(FROM|JOIN|UPDATE|INTO|TABLE) (users|premises|bookings|collaborators|service_orders|kb_articles|kb_chat_sessions|kb_documents)`.

Allowlist (для редких legitimate edge cases) — inline `# arch-allow: <reason ≥10 chars>`.

Скрипт сам покрыт unit-тестами в `tests/arch-constraint/` (4 fixture
файла + `test_runner.sh`).

Локально: `make arch-check` из `backend/`.

## Развитие документа

После landing'а E1 этот файл расширится диаграммой компонентов,
описанием HTTP-flow эскалации из kb-search и схемой БД ядра.
