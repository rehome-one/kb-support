# ADR-0014: Провизорные контракты upstream-сервисов претензий (для E10-7)

## Статус

- [x] **Принято**
- **Дата:** 2026-06-09
- **Автор:** Агент-Разработчик; принято Архитектором (Evgeniy)
- **Согласовано Архитектором:** да, 2026-06-09 (4 решения U1-U4 ратифицированы)

> Этот ADR уточняет **ADR-0013 Решение 7** (upstream config-gated seam) для под-задачи
> **E10-7 (#197)**: фиксирует провизорные контракты внешних сервисов претензий и 4 решения
> по их проводке. Прецедент формата — **ADR-0006** (провизорные контракты platform/kb-search
> для E3). Боевые контракты будут уточнены при провижининге (ops); до тех пор клиенты
> **config-gated и инертны**, как #77/#79.

## Контекст

E10-7 строит исходящие (outbound) клиенты к upstream-сервисам платёжного/юридического
контура: `BankProvider.releasePayout`, `PaymentReleaseChecker`, `AcceptanceAct`,
`FinancialLedger`, передача события в страховую (FR-9.4/9.6/9.8, §3.2.1, §3.11). Эти
сущности **ещё не готовы** (TD-UP-001) — их контракты upstream не зафиксированы.

**Инвариант финмодели (FR-9.8, ADR-0005, ADR-0013).** kb-support **хранит решение и
ссылки (UUID), деньги НЕ считает**. Выплаты, регресс, пеня за рассрочку (D2), проводки
ledger — платёжный/юридический контур. Связь только по сети, **без FK к чужим БД**
(арх-константа).

**Инвариант устойчивости (NFR-4.4).** Сбой/недоступность соседа не должен ломать работу
kb-support. Клиенты — поверх `ResilientHttpClient` (AT-003: timeout→circuit-breaker→retry),
config-gated по пустому токену (как platform/kb-search/kb-files), инертны до ops.

**Граница с E10-8 (#198).** Входящий webhook страховщика (приём страхового события,
`channel=INSURER_WEBHOOK`) — **inbound, в E10-8**. E10-7 — только **outbound** (наши вызовы
вверх) + доставка решения заявителю в ЛК.

## Решение

**U1 — Декомпозиция: 2-3 PR под #197.** ADR-0014 (этот) → **PR-1** (платёжный путь:
`releasePayout` + `PaymentReleaseChecker`, врезка в PAYOUT_PENDING→PAID) → **PR-2** (остаток:
`AcceptanceAct` read, `FinancialLedger` record, доставка решения в ЛК, outbound-уведомление
страховщика). Каждый PR обозрим, по паттерну дробления #145.

**U2 — Провизорные контракты фиксируются здесь** (таблица ниже), помечены
`# provisional contract` в адаптерах (как #71). Боевой контракт — при провижининге (ops),
тогда же реальный m2m-токен (#77). До этого все клиенты config-gated, инертны.

**U3 — `releasePayout` = fire-after best-effort.** Переход PAYOUT_PENDING→PAID («4 глаза»,
D6) завершается СРАЗУ (внутреннее решение). Реальный вызов `releasePayout` — ПОСЛЕ ответа
(паттерн #72 return-to-chat): фоновый таск, никогда не роняет переход; при подтверждении
пишет `linked_payment_id`. Дубль-проверка «двух глаз» — на стороне upstream (D6). Durable-
доставка (Dramatiq) — follow-up #79. Сбой/выключенная интеграция НЕ откатывает PAID
(NFR-4.4): «деньги ушли» подтверждается асинхронно, не блокирует state-machine.

**U4 — `PaymentReleaseChecker` = информационно, НЕ блокирует.** Результат проверки
(`clearable`/`reason`) хранится в `TicketCaseDetails.payload` и показывается оператору, но
case_state-машину **не блокирует**. Жёсткий гейт PAID связал бы наш детерминированный переход
с доступностью соседа (нарушение NFR-4.4); при бизнес-необходимости — отдельный follow-up.

### Провизорные контракты (уточняются при провижининге)

| Сервис | Операция (provisional) | Семантика | Деградация |
|---|---|---|---|
| `BankProvider` | `POST /api/v1/payouts` `{ticket_id, amount, currency:"RUB", reference}` → 202 `{payment_id}` | releasePayout (U3, fire-after) → `linked_payment_id`; идемпотентность по ticket_id+decision | мутация → raise из base, ловится фоновым таском (лог, не роняет PAID) |
| `PaymentReleaseChecker` | `GET /api/v1/clearance?ticket_id=…` → 200 `{clearable, reason?}` | информационно (U4), флаг в payload | read → None + WARN |
| `AcceptanceAct` | `GET /api/v1/acts/{acceptance_act_id}` → 200 `{id, kind, signing_status, …}` | резолв акта для ACCEPTANCE_ACT (E10-9) → `signing_status` | read → None + WARN |
| `FinancialLedger` | `POST /api/v1/entries` `{ticket_id, decision, approved_amount, payment_id?}` → 202 `{entry_id}` | проводка-ссылка (фиксация, деньги не считаем) | fire-after best-effort, лог |
| Insurer (outbound) | `POST /api/v1/events` `{ticket_id, insurance_event_id}` → 202 | передача события в страховую (FR-9.6) | fire-after best-effort, лог |

ПДн в логи/метрики upstream-клиентов не пишем (только id/operation/status; ФЗ-152).

## Альтернативы

1. **Inline-провизорные формы без ADR** — отклонено: решение по 5 контрактам не зафиксировано
   отдельно, reviewer'у труднее проверить полноту; ADR-0006 задал прецедент.
2. **`releasePayout` inline-blocking (PAID ждёт успеха)** — отклонено: связывает state-machine
   с доступностью upstream, нарушает NFR-4.4; дубль-чек уже на стороне банка (D6).
3. **`PaymentReleaseChecker` как жёсткий гейт PAID** — отклонено: та же связанность с upstream;
   при недоступности соседа заявка зависла бы. Гейт — возможный follow-up при бизнес-требовании.
4. **Один большой PR на все 5 интеграций** — отклонено в пользу 2-3 обозримых PR (U1).

## Последствия

### Положительные

- Чистые точки врезки upstream зафиксированы, инертны до ops (как E3/E6/E7) — kb-support
  готов к провижинингу без переписывания.
- Устойчивость (NFR-4.4): сбой/выключение соседа не ломает claims-lifecycle.
- Финмодель-инвариант соблюдён: только ссылки/id, деньги не считаем.

### Отрицательные / компромиссы

- Провизорные контракты могут измениться при провижининге — потребуется правка адаптеров
  (локализована мапперами `# provisional contract`, как #71).
- `releasePayout` fire-after: окно между PAID и подтверждением выплаты, `linked_payment_id`
  заполняется асинхронно (durable-гарантия — #79).

### Технические следствия

- Новые пакеты `backend/src/api/clients/{bank,payment_checker,acceptance_act,financial_ledger,insurer}/`
  (Protocol + Http-adapter + factory-фабрика `get_*_client() -> Client | None`, config-gate по пустому токену).
- Config-ключи `*_api_base_url` / `*_api_token` (пусто = off) в `config.py`.
- Врезка: `releasePayout`/ledger — fire-after в `actions._approve_payout` (PAID); `PaymentReleaseChecker` —
  при входе в PAYOUT_PENDING (флаг в payload); `AcceptanceAct` — E10-9; доставка решения — поверх
  `decision_notified_at`. m2m-токен — StaticTokenProvider (dev/test) → real ClientCredentials #77.
- Миграций НЕТ (UUID-поля claims уже на `Ticket` с E10-1). OpenAPI не меняется (контракт полный).

## Ссылки

- ТЗ: §3.2.1, §3.11, §4.9 FR-9.4/9.6/9.8, §8.1; Договор найма 5.7/5.8
- Связанные ADR: ADR-0013 (Решение 7), ADR-0006 (прецедент провизорных контрактов), ADR-0005 (двухконтурность), ADR-0010 Реш.4 (мутации → raise)
- Issue: #197 (E10-7); TD-UP-001 (upstream не готов); follow-up #77 (m2m), #79 (durable Dramatiq)
