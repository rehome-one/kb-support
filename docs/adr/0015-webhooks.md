# ADR-0015: Доставка webhook-событий и приём webhook страховщика (E10-8)

## Статус

- [ ] Предложено
- [x] **Принято**
- **Дата:** 2026-06-10
- **Автор:** Агент-Разработчик; принято Архитектором (Evgeniy)
- **Согласовано Архитектором:** да, 2026-06-10 (4 решения — объём, модель подписок, механизм, триггер insurance_event — ратифицированы; подпись «Принято» проставлена).

> Этот ADR фиксирует контракт **доставки исходящих webhook-событий** kb-support и
> **провизорный контракт приёма webhook страховщика** для под-задачи **E10-8 (#198)**.
> Уточняет **ADR-0013** (webhook-события «это E10») и снимает границу **ADR-0014 §«Граница с
> E10-8»** (inbound страховщика). Прецедент провизорного контракта — **ADR-0006/0014**.
> Боевые контракты подписчиков/страховщика — при провижининге (ops); до тех пор доставка
> **config-gated и инертна** (как #77/#79).

## Контекст

Контракт (`docs/openapi.yaml:1533-1584` `/api/v1/support/webhooks`, схема `WebhookSubscription`
`:3271-3306`) описывает **подписку** на webhook (url/events/secret/is_active, scope=`staff_admin`,
доставка «с HMAC-подписью, заголовок `X-Signature`») и enum из 13 событий, в т.ч. три claims-события:
`ticket.case_decided`, `ticket.payout_released`, `ticket.insurance_event`. Но контракт **не
специфицирует**: формат доставляемого payload событий, алгоритм/формат HMAC, anti-replay,
durability, ретраи. Inbound-эндпоинта приёма события от страховщика в контракте нет вовсе.
Webhook-инфраструктуры в коде сейчас НЕТ — строим с нуля.

**Инвариант финмодели (FR-9.8, ADR-0005/0013).** kb-support хранит решение/ссылки (UUID), деньги
не считает. Webhook несёт только факт+id, не финрасчёт.

**Инвариант NFR-1.3 / ФЗ-152.** Внутренние заметки (`is_internal=true`) и ПДн заявителя
(email/phone/паспорт/`rating_comment`) **не должны утечь** внешнему подписчику.

**Инвариант устойчивости (NFR-4.4).** Недоступность/сбой подписчика не ломает lifecycle заявки.

## Решение

**D1 — Объём E10-8 = исходящие события + inbound страховщик.** Реализуем (а) эмиссию трёх
исходящих claims-событий подписчикам и (б) приём webhook страховщика (`channel=INSURER_WEBHOOK`).
Связка: inbound от страховщика проставляет `Ticket.insurance_event_id` → это **триггер** outbound
`ticket.insurance_event` (см. D6). Снимает «Границу с E10-8» из ADR-0014.

**D2 — Модель подписок = полная по контракту.** Таблица `WebhookSubscription` (своя БД, без FK) +
`POST/GET /api/v1/support/webhooks` (scope=`staff_admin`, как admin-эндпоинты #86/#126) +
repository. `secret` отдаётся **только при создании** (контракт), наружу в list/логи не утекает.

**Декомпозиция (4 PR, порядок строгий):**
`ADR-0015` (этот) → **PR-A** (таблица `WebhookSubscription` + миграция + CRUD-роутер + HMAC-signer
+ контракт-тест AT-002) → **PR-B** (эмиссия 3 событий + диспетчер доставки + врезки в
`decide`/newly-PAID/заполнение `insurance_event_id`) → **PR-C** (inbound insurer endpoint,
провизорный). Каждый PR ≤800 строк, **двухфазный коммит** (claims/security — однофазный не
применяется).

**D3 — Подпись = HMAC-SHA256 с anti-replay (Stripe-style).** Защита от подмены И воспроизведения:
- Заголовки доставки: `X-Webhook-Event`, `X-Webhook-Delivery` (uuid доставки),
  `X-Webhook-Timestamp` (unix-секунды), `X-Signature: t=<unix>,v1=<hex>`.
- Подписываемая строка = `"{t}.{raw_json_body}"`, `v1 = HMAC_SHA256(secret, signed_string)` в hex.
- Секрет — per-subscription (`WebhookSubscription.secret`).
- Приёмник обязан отвергать при расхождении timestamp > **300 с** (tolerance) и при несовпадении
  подписи. *Обоснование (условие ревью У2):* голый timestamp-заголовок не покрыт HMAC → не даёт
  replay-защиты; включение `t` в подписываемую строку — то, что её обеспечивает.

**D4 — Доставка = fire-after best-effort, config-gated, durable→#79.** Эмиссия — фоновый таск после
commit (паттерн E10-7 `decision_dispatch`/`payout_dispatch`): per-подписка свой `httpx.AsyncClient`
поверх `ResilientHttpClient` (AT-003: timeout→breaker→retry), **never-raise** (лог WARN, не роняет
запрос). Ретраи — только in-flight (внутри `ResilientHttpClient`); durable-гарантия доставки
(Dramatiq, переживание рестарта) — **follow-up #79**. Gate: нет активных подписок на событие →
seam инертен. Сбой/выключение доставки НЕ откатывает state-машину (NFR-4.4).

**D5 — Payload = whitelist-конверт без ПДн.** Конверт:
`{event, delivery_id, occurred_at, ticket_id, ticket_number, data:{…}}`. `data` — **только whitelist
полей** (id/суммы/статусы, как в карточке оператора), **НЕ** сериализация модели. Запрещено в
payload: `is_internal`-заметки, тело переписки, ПДн заявителя, `rating_comment` (условие ревью У8,
NFR-1.3/ФЗ-152). Отдельный security-тест: webhook на заявку с internal-заметкой её контент не несёт.

**D6 — Дедуп события = per `(ticket, event)` через `custom_fields` блок `"webhooks"` реассайном.**
Маркер пишется реассайном словаря (`ticket.custom_fields = dict(...)`, не in-place — колонка без
`MutableDict`, урок `notifications/dedup.py` M1), в общем блоке, не перетирая `notifications`-маркеры.
**Согласование с REOPENED (условие ревью У16):** легитимное повторное решение после REOPENED
(`case_decided #2`) подавляться не должно. Реализация PR-B обязана проверить фактическое поведение
`actions.decide()` (бросает 409 при уже выставленном `decision`, `actions.py:276`): если `decision`
сбрасывается при REOPENED — дедуп-маркер сбрасывается зеркально (как M2 в `dispatcher.py`); если не
сбрасывается — повторного события не возникает и дедуп тривиален. Выбранная семантика фиксируется в
PR-B + тест `case_decided → reopen → case_decided`.

**D7 — `ticket.payout_released` = факт внутреннего решения о выплате (PAID), НЕ банк-подтверждение.**
Событие эмитится на переходе case_state PAYOUT_PENDING→PAID («4 глаза», D6 ADR-0013), когда реальный
`linked_payment_id` ещё может быть пуст (он приходит асинхронно — fire-after `releasePayout`/inbound/
#79, ADR-0014 U3). Payload и docstring обязаны это **явно** помечать (условие ревью У10): подписчик
не должен трактовать событие как «деньги фактически ушли».

**D8 — `ticket.insurance_event` триггерится заполнением `Ticket.insurance_event_id`.** Эмиссия при
проставлении `insurance_event_id` на claims-заявке INSURANCE (через inbound страховщика — PR-C, либо
оператором). Payload несёт **только** `ticket_id` + `insurance_event_id` (без страховых ПДн: полис/
ФИО/медданные — условие ревью У11).

**Inbound webhook страховщика (провизорный, PR-C).** `POST /api/v1/support/insurer-events` (нет в
openapi → фиксируется здесь, как `from-email`): m2m `kind=SERVICE`-only + **верификация входящей
подписи** (симметричный HMAC по общему `insurer_inbound_secret`); посторонний принципал / битая
подпись → 401/403 (anti-spoofing, условие ревью У13). Идемпотентность по `insurance_event_id`
(повтор не двоит эффект). Находит claims-заявку INSURANCE, проставляет `insurance_event_id` +
history-событие → триггерит outbound `ticket.insurance_event` (D8). Маршрутизация INSURER_WEBHOOK на
команду — через AutomationRule (ADR-0013 D8), не хардкодом.

### Провизорные контракты (уточняются при провижининге)

| Направление | Операция (provisional) | Семантика | Безопасность / деградация |
|---|---|---|---|
| Outbound (нам→подписчик) | `POST <subscription.url>` тело = конверт D5, заголовки D3 → ожидаем 2xx | доставка события подписке | HMAC+timestamp D3; fire-after never-raise (D4); лог только id |
| Inbound (страховщик→нам) | `POST /api/v1/support/insurer-events` `{ticket_ref|insurance_event_id, …}` → 202 | приём страхового события → `insurance_event_id` (D8) | m2m kind=SERVICE + verify HMAC; идемпотентность по `insurance_event_id`; 401/403 anti-spoofing |

ПДн в логи/метрики webhook-путей не пишем (только `ticket_id`/`event`/`delivery_id`/`status`; ФЗ-152).

## Альтернативы

1. **MVP: один `webhook_url` из Settings** (без таблицы подписок) — отклонено Архитектором: расходится
   с контрактом (`POST /webhooks` остался бы нереализован, дрейф спеки).
2. **HMAC только по телу, без timestamp** — отклонено: не даёт anti-replay (У2); дёшево закрыть сейчас.
3. **Сериализация модели целиком в payload** — отклонено: утечка `is_internal`/ПДн (NFR-1.3); только whitelist.
4. **Durable Dramatiq-доставка сейчас** — отклонено Архитектором: брокер не поднят (#79); fire-after,
   как весь E10.
5. **Inbound insurer как отдельный эпик** — отклонено: связан с триггером `insurance_event` (D8),
   логичнее в E10-8.

## Последствия

### Положительные
- Контракт `/webhooks` реализуется дословно; формат подписи/payload зафиксирован до кода.
- NFR-1.3/ФЗ-152 под защитой (whitelist payload + security-тест).
- NFR-4.4: сбой подписчика/страховщика не ломает claims-lifecycle.
- Inbound→outbound связка `insurance_event` замкнута.

### Отрицательные / компромиссы
- Провизорные формы payload/inbound могут измениться при провижининге (локализуются билдерами/адаптером,
  помечены `# provisional contract`).
- Fire-after: окно потери доставки при рестарте до #79 (durable). Приемлемо — события идемпотентны на
  стороне подписчика по `delivery_id`/`insurance_event_id`.

### Технические следствия
- Новый пакет `backend/src/api/webhooks/` (models/repository/schemas/router/signing/events/dispatcher).
- Миграция `WebhookSubscription` (PR-A); `import api.webhooks.models` в `alembic/env.py`.
- Config: `webhook_*` (delivery toggle/tolerance) + `insurer_inbound_secret`/`insurer_inbound_*`
  (пусто = off). Переиспользуют `client_*` (timeout/breaker/retry) и `clients/factory.build_resilient_client`.
- Врезки эмиссии (после commit): `case_decided` → `router.py` `decide_ticket` (~:786);
  `payout_released` → `router.py` `transition_case_state` newly-PAID (~:753); `insurance_event` → при
  заполнении `insurance_event_id` (PR-C).
- OpenAPI: `/webhooks` уже в контракте (PR-A под него + AT-002); inbound `/insurer-events` добавляется
  провизорно (PR-C) + реген `frontend/lib/api/schema.d.ts`.

## Ссылки

- ТЗ: §4.9 FR-9.6 (страховой контур), webhooks-контракт; NFR-1.3, NFR-4.4; ФЗ-152
- Связанные ADR: ADR-0013 (claims, webhook-события «E10», D8 маршрутизация), ADR-0014 (граница inbound
  страховщика; fire-after прецедент U3), ADR-0006 (прецедент провизорных контрактов), ADR-0010 Реш.4
  (мутации → raise), ADR-0005 (двухконтурность, финмодель)
- Issue: #198 (E10-8); follow-up #79 (durable Dramatiq), #77 (m2m token)
- Ревью плана #198: APPROVE-WITH-CONDITIONS, условия У1–У18 (anti-replay У2, payload-whitelist У8,
  payout_released-семантика У10, дедуп-vs-REOPENED У16, inbound anti-spoofing У13)
