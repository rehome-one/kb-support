# State of Code Report — kb-support

> Артефакт Phase 0 — baseline для разработки модуля службы поддержки reHome.
> Живой документ: обновляется по ходу сессий (как `docs/state-of-code.md`
> в kb-platform).

**Статус:** ✅ Утверждено
**Дата:** 2026-05-30
**Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
**Утверждено Архитектором:** 2026-05-30 (подтверждение в чате при bootstrap'е)

> **TL;DR:** Модуль — **greenfield**. Существующего кода kb-support нет.
> Репозиторий `rehome-one/kb-support` создан 2026-05-30 и содержит только
> handoff-документы, ADR'ы, процессные файлы (CLAUDE.md / CLAUDE-REVIEWER.md /
> CI baseline). Phase 1 начинается с E1 «Ядро заявок» по ТЗ kb-support v2.2.

---

## 1. Структура репозиториев

| Репозиторий | URL | Описание |
|---|---|---|
| `rehome-one/kb-support` | https://github.com/rehome-one/kb-support | **Этот репо.** Модуль службы поддержки. |
| `rehome-one/rehome-kb-platform` | https://github.com/rehome-one/rehome-kb-platform | **Соседний.** База знаний (kb-search/kb-wiki/kb-files/kb-vault/kb-auth/...). Используется по API. |

Архитектурная константа (§1.4, NFR-4.4, ADR-0005 ТЗ): **никаких shared
таблиц, никакого shared кода**. Связь с rehome-kb-platform и rehome.one —
только HTTP API.

## 2. Технологический стек (целевой)

Греenfield — ничего не установлено. Целевой стек по ADR-0001 (reference-копия
из kb-platform), со статусом «не подключено».

### Backend

| Компонент | Целевое | Фактическое на bootstrap |
|---|---|---|
| Python | 3.12+ | ❌ |
| FastAPI | основной фреймворк (микросервис) | ❌ |
| Dramatiq + Redis | очереди (SLA-таймеры, IMAP) | ❌ |
| PostgreSQL | 16+ (своя БД, не shared) | ❌ |
| HTTP-клиент к external API | httpx async + Redis-кеш | ❌ |
| Keycloak | через API kb-auth | ❌ |
| MinIO | через API kb-files | ❌ |

### Frontend

| Компонент | Целевое | Фактическое |
|---|---|---|
| Next.js | 14+ (App Router) | ❌ |
| React | 18+ | ❌ |
| TypeScript | strict | ❌ |
| Tailwind CSS | latest | ❌ |

Frontend подключается в kb-staff кабинет как отдельный раздел через SSO
(не одна и та же кодовая база с kb-staff).

### Внешние сервисы и интеграции

| Сервис | Назначение | Категория ADR-0001 | DPA | Готовность |
|---|---|---|---|---|
| rehome-kb-platform (kb-search) | Эскалация AI-чата → создание тикета | A (соседний внутренний) | N/A | ✅ работает |
| rehome-kb-platform (kb-wiki) | Read-only статьи для шаблонов | A | N/A | ✅ |
| rehome-kb-platform (kb-files) | MinIO вложения | A | N/A | ✅ |
| rehome-kb-platform (kb-auth) | Keycloak SSO | A | N/A | ✅ |
| rehome.one platform API | User / Premises / Booking / Collaborator / ServiceOrder | A | N/A | ⚠️ интерфейс ещё не зафиксирован |
| Email (IMAP) | Канал email (E7) | A (свой парсер в РФ) | N/A | ❌ E7 |
| BankProvider.releasePayout | Выплата по COMPENSATION (E10) | C | ⚠️ требуется | ❌ E10 + upstream |
| Insurer webhook | Страховое событие (E10) | C | ⚠️ требуется | ❌ E10 + upstream |
| Exolve SMS-OTP | ACCEPTANCE_ACT подписание (E10) | C | ⚠️ требуется | ❌ E10 + upstream |

## 3. Тестовое покрытие (baseline)

**0 %** — ни одного теста (нет кода).

**Целевые значения** (NFR ТЗ + наследовано из kb-platform):

- Бизнес-логика: **≥ 80 %** (блок merge при < 60 %).
- UI-компоненты: **≥ 60 %** (блок merge при < 40 %).
- Security-критичные пути (`access_level`, `is_internal=true`, claims/decision):
  отдельные тесты на попытки обхода прав — **обязательно**.

## 4. Существующие сущности и модели данных

**Никаких** — greenfield. Целевые сущности зафиксированы в ТЗ:

- **Ticket** (§3.1) — центральная сущность, поля 3.1 + 3.1.1 (claims).
- **TicketMessage** (§3.5) — переписка + внутренние заметки.
- **TicketHistory** (§3.7) — неизменяемый аудит.
- **CannedResponse** (§3.6) — шаблоны ответов.
- **SLAPolicy** (§3.8) — политики SLA.
- **AutomationRule** (§3.9) — правила автоматизации.
- **TicketCaseDetails** (§3.11) — payload претензионных типов 1:1 к Ticket.

User / Premises / Booking / Collaborator / ServiceOrder — **не дублируем**
(§3.10 ТЗ). Только ссылки + HTTP-клиент.

## 5. Известные баги и техдолг (Phase 0)

| ID | Описание | Severity | Влияние |
|---|---|---|---|
| TD-OAS-001 | handoff `04_openapi.yaml` (v1.1, из ТЗ Приложение A) содержит legacy `nullable: true` (deprecated в OpenAPI 3.1). Redocly strict lint падает с 28 ошибками. | P3 | Handoff yaml — immutable артефакт Архитектора, не правится. На E1 при подготовке production `docs/openapi.yaml` будут нормализованы (`type: [<original>, "null"]`). CI advisory на handoff (`continue-on-error`), strict на production yaml |
| TD-RBT-001 | Архитектурная константа держится на дисциплине агентов + Reviewer чек-листе. **Технически** ничто не мешает кому-то импортнуть `from rehome_kb_platform...` или открыть прямой SQL к чужой БД. | P2 | Reviewer обязан грепом ловить такие импорты; план — на E1 добавить CI-проверку, грепающую запрещённые импорты. См. AT-001 ниже |
| TD-BPA-001 | Нет технической защиты ветки `main` (унаследовано с kb-platform — GitHub Free). Force-push, прямой commit в main технически возможны | P2 | Дисциплина CLAUDE.md / CLAUDE-REVIEWER.md. Если в будущем org перейдёт на платный тариф — добавить ruleset |
| TD-PA-001 | rehome.one platform API (для User / Premises / Booking / Collaborator) — интерфейс ещё не зафиксирован. | P1 | Блокирует E3 (full chat integration с context'ом заявителя). E1/E2 могут идти на mock-API |
| TD-UP-001 | Upstream-зависимости для E10 (AcceptanceAct, PaymentReleaseChecker, FinancialLedger, BankProvider.releasePayout, обеспечительный платёж, регрессное обязательство, webhook страховщика) — не реализованы в платформе. | P1 | E10 в режиме «фиксация решения + ссылки» (§8.1 ТЗ); фактическая выплата подключается по готовности upstream |
| TD-OQ-001 | 3 открытых вопроса по претензионным типам (§8.1 ТЗ): окно 14 дн, плата 0.2 %/день, scope «claims-оператор». | P2 | Не блокирует E1-E9. Перед E10 — ADR'ы с решениями Архитектора |

## 6. Соответствие ФЗ-152 (текущее состояние)

| Требование | Статус | Замечания |
|---|---|---|
| Шифрование ПДн в покое (AES-256) | ⏳ PENDING | Нет БД |
| Шифрование в передаче (TLS 1.3) | ⏳ PENDING | Нет деплоя |
| `TicketHistory` + audit_log для операций с ПДн | ⏳ PENDING | Реализуется в E1 |
| Серверы в РФ | ⏳ PENDING | Не выбран провайдер |
| DPA с внешними сервисами категории C | ❌ NOT STARTED | По мере подключения (E10) |
| Маскирование ПДн (email/phone/passport) перед persistence и в логах | ⏳ PENDING | Reuse паттерна `mask_pii` из kb-platform (свой код, не shared) |
| Хранение TicketHistory 5 лет | ⏳ PENDING | NFR-1.4 ТЗ |

**Итого:** соответствие ФЗ-152 на момент baseline = **0 %**. Ожидаемо для
greenfield.

## 7. Что НЕТ в существующем коде (отсутствующее)

Всё перечисленное в §3 ТЗ — отсутствует, реализуется с нуля по этапам:

- ❌ Backend FastAPI сервис + БД схема
- ❌ Frontend Next.js (рабочее место оператора)
- ❌ Worker Dramatiq (SLA-таймеры, IMAP-парсер)
- ❌ HTTP-клиенты к external API (rehome.one, kb-search, kb-wiki, kb-files,
  kb-auth)
- ❌ OpenAPI production spec (docs/openapi.yaml) — будет на E1
- ❌ CI workflows активные (сейчас заглушки с `if: exists`)
- ❌ Контрактные тесты против handoff yaml

## 8. План этапов (повтор из ТЗ §7)

| Этап | Объём | Срок (ориентир) |
|---|---|---|
| E1 | Ядро заявок: Ticket, TicketMessage, статусы, CRUD API, TicketHistory, OpenAPI production | 2 нед |
| E2 | Рабочее место оператора (Next.js, подключение в kb-staff через SSO) | 2 нед |
| E3 | Интеграция с kb-search: from-chat, возврат ответа, HTTP-клиенты к platform | 2 нед |
| E4 | SLA: SLAPolicy, таймеры Dramatiq, индикация, эскалация | 1.5 нед |
| E5 | Автоматизация: AutomationRule, маршрутизация, автоназначение | 1.5 нед |
| E6 | Шаблоны и база знаний: CannedResponse, связь с kb-wiki | 1 нед |
| E7 | Каналы email/форма: свой IMAP-парсер | 2 нед |
| E8 | Аналитика: панель супервайзера, отчёты, Grafana | 1.5 нед |
| E9 | Оценка качества: рейтинги, уведомления | 0.5 нед |
| E10 | Претензионные типы: case_state, decision, claims SLA, «4 глаз» | 2-3 нед |

Итого ~16-17 недель.

## 9. Архитектурные следствия для следующих PR

### AT-001 — Проверка архитектурной константы в CI (E1)

На E1 в CI добавить шаг, грепающий запрещённые импорты / SQL:

```bash
# Запрещённые импорты
grep -rE 'from (rehome_kb_platform|kb_platform|kb_search|kb_wiki|kb_vault)' \
  backend/src --include='*.py' && exit 1

# Запрещённые SQL к чужим таблицам
grep -rE '(FROM users|FROM premises|FROM bookings|FROM collaborators)' \
  backend/src --include='*.py' --include='*.sql' && exit 1
```

Делает TD-RBT-001 техническим, а не только дисциплинарным.

### AT-002 — Контрактные тесты по OpenAPI (E1)

Использовать Prism mock против handoff `04_openapi.yaml`. На E1 backend
должен пройти контрактные тесты против spec'а. Это фиксирует API и снижает
риск drift.

### AT-003 — Graceful degradation HTTP-клиентов (E3)

Каждый клиент к external API должен иметь:
- timeout
- retry с exponential backoff
- circuit breaker
- кеш в Redis с разумным TTL (не отдавать stale data при критичных
  операциях — claims/decision)
- метрики (success/failure rate, latency)

Тестировать с external-API в down-сценарии: kb-support должен продолжать
работать (с деградированным функционалом), а не падать.

## 10. Историческая справка

- **2026-05-30** — bootstrap repo `rehome-one/kb-support`, Phase 0
  baseline создан. Handoff: ТЗ v2.2 + OpenAPI v1.1 + ADR-0005.
  Reference-копии ADR-0001/0003/0004 из kb-platform.
