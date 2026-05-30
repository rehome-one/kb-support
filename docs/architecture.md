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

## Развитие документа

После landing'а E1 этот файл расширится диаграммой компонентов,
описанием HTTP-flow эскалации из kb-search и схемой БД ядра.
