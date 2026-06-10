# ADR-0017: GUARANTEE (SYSTEM-триггер), INSURANCE (вердикт страховщика), insurer-outbound (E10-10)

## Статус

- [ ] Предложено
- [x] **Принято**
- **Дата:** 2026-06-10
- **Автор:** Агент-Разработчик; принято Архитектором (Evgeniy)
- **Согласовано Архитектором:** да, 2026-06-10 (4 решения — GUARANTEE-inbound, INSURANCE-вердикт, insurer-outbound, регресс-ссылки — ратифицированы; подпись «Принято» проставлена).

> Этот ADR детализирует **ADR-0013** (GUARANTEE/INSURANCE — «это E10»; D2 пеня→платёжный контур; D8 маршрутизация)
> и **ADR-0014** (insurer-outbound `POST /api/v1/events`, l.67) для под-задачи **E10-10 (#200)** (FR-9.5/9.6,
> §3.3.2/§3.3.3). Прецедент провизорных контрактов/отложенных инвариантов — ADR-0006/0015/0016. Боевые контракты —
> при провижининге; до тех пор всё **config-gated и инертно** (#77/#79).

## Контекст

Домен GUARANTEE/INSURANCE готов с E10-1: `CaseType`/`TicketType` GUARANTEE/INSURANCE, `TicketChannel`
SYSTEM/INSURER_WEBHOOK/LK_CLAIM, колонки `regress_obligation_id`/`policy_id`/`insurance_event_id` (плоские, UUID без FK),
`GuaranteePayload` (missed_payment_id/guarantee_payout_id/regress_due_at/late_fee_accrued/guarantee_paused),
`InsurancePayload` (insurer_claim_ref/insurer_status/event_payload). **В коде НЕТ:** приёма GUARANTEE-сигнала,
фиксации вердикта страховщика, insurer-outbound-клиента.

**ТЗ:** GUARANTEE-тикет создаётся **системным триггером только при исключениях** (мошенничество 5.7.7-б, просрочка
регресса >14 дн 5.7.6, приостановка гарантии 5.7.8) — исключения детектирует **платёжный контур**, не оператор
(FR-9.5, §3.3.2). INSURANCE: **решение по выплате — за страховщиком** (FR-9.6, §3.3.3); оператор сопровождает,
передаёт материалы. **Инвариант FR-9.8/D2:** kb-support хранит решение/ссылки, деньги/пеню не считает.

## Решение

**D1 — GUARANTEE = новый m2m-inbound `POST /api/v1/support/guarantee-events`.**
От платёжного контура: kind=SERVICE (anti-spoofing, 403) + HMAC fail-closed по **`guarantee_inbound_secret`**
(config-gated, отдельный ключ — другой контрагент, не insurer), дословно паттерн insurer-events (E10-8). Системно
создаёт GUARANTEE-тикет через `TicketRepository.create` (актор `CLAIMS_ACTOR_ID`, `PrincipalKind.OPERATOR`,
channel=SYSTEM → finance по D8; intake → case_state=CLAIM_SUBMITTED). Оператор/generic POST /tickets отвергнут
(ТЗ «системный»). Инертно до ops.

**Идемпотентность (A1).** Заявки при первом приёме ещё нет → reference хранится в
`custom_fields["guarantee_reference"]`; перед созданием — `find_guarantee_by_reference` (SELECT по
`type='GUARANTEE' AND custom_fields->>'guarantee_reference'=:ref`), найдена → no-op (возврат существующей).
Поиск+создание в одной транзакции. **Гонка параллельных ретраев (select-then-insert без constraint) —
hardening-follow-up:** частичный uniq-индекс на `(custom_fields->>'guarantee_reference') WHERE type='GUARANTEE'`
при провижининге боевой интеграции (прецедент M1 ADR-0016). **Без индекса нет IntegrityError-recovery-ветки**
(в отличие от chat-дедупа) — идемпотентность держится на сериализации инертного/config-gated режима. Без миграции сейчас.

**D2 — INSURANCE-вердикт = расширение inbound `insurer-events`.**
*(Проектируемое поведение E10-10 — текущий `webhooks/inbound.py` пишет только `insurance_event_id`; ниже — после расширения.)*
`InsurerEventIngest` дополняется опц. `insurer_status?`/`insurer_decision?`. Вердикт страховщика → фиксируется в
`InsurancePayload.insurer_status` + **системно двигает case_state** по машине E10-2. **Наш `decide()` НЕ применяем,
`ticket.decision` НЕ трогаем** — это наш внутренний вердикт (FR-9.3, legal/finance), а решение по INSURANCE — страховщика.
**Запрещённый переход в webhook → WARN-лог + сохранить только `insurer_status` (ответ 202, не 422)** — упавший inbound =
потеря доставки; используем `is_allowed_case_transition` как предикат, НЕ `transition_case_state` (он бросает 422).
Системный маппинг — строго ПОСЛЕ idempotency-early-return по `insurance_event_id` (повтор не двигает state дважды).

**D3 — insurer-outbound = новый `clients/insurer/` + врезка.**
Контракт ADR-0014:67: `POST /api/v1/events {ticket_id, insurance_event_id}` → 202, fire-after best-effort.
Клиент по эталону `clients/bank` (мутирующий: **деградация = raise**, НЕ None; ловится фоновым таском never-raise),
config-gate `insurer_api_token`. Точка эмита — **впервые вход INSURANCE-заявки в `UNDER_REVIEW`**: чистый предикат
`is_insurance_submitted(ticket, old_case_state)` в `case_state_machine.py` (`type==INSURANCE AND case_state==UNDER_REVIEW
AND old!=UNDER_REVIEW`, edge-triggered как `is_newly_paid`; без копий). Тело — только `{ticket_id, insurance_event_id}`
(id-only, ПДн нет; logи id/operation/status). В openapi НЕ описывается (исходящий вызов к соседу).

**D4 — Регресс GUARANTEE = фиксация-ссылки при создании.**
**Плоские колонки Ticket:** `regress_obligation_id`, `policy_id` (ставит платёжный контур — сохраняем).
**`GuaranteePayload`:** `missed_payment_id`, `guarantee_paused`, `late_fee_accrued` (**число-ссылка, приходит ГОТОВЫМ** —
пеню НЕ вычисляем, D2/FR-9.8). `regress_due_at` **и** `guarantee_payout_id` при создании НЕ трогаем — `regress_due_at`
пишет существующий `_record_regress_due_at` при PAID (E10-6), `guarantee_payout_id` ставит платёжный контур позже.
Создание ≠ выплата, конфликта нет.

### Провизорные контракты (уточняются при провижининге)

| Направление | Операция (provisional) | Семантика | Безопасность / деградация |
|---|---|---|---|
| Inbound (платёжный→нам) | `POST /support/guarantee-events` `{exception_kind, reference, missed_payment_id?, regress_obligation_id?, late_fee_accrued?, requester_id?}` → 202 Ticket | системное создание GUARANTEE (D1) | m2m kind=SERVICE + verify HMAC; идемпотентность по reference; fail-closed |
| Inbound (страховщик→нам) | `POST /support/insurer-events` `{…, insurer_status?, insurer_decision?}` → 202 | вердикт страховщика → insurer_status + case_state (D2) | m2m+HMAC; illegal-transition→лог не raise; идемпотентность по insurance_event_id |
| Outbound (нам→страховщик) | `POST /api/v1/events {ticket_id, insurance_event_id}` → 202 | передача события в страховую (D3) | мутация→raise из base, фоновый таск never-raise; config-gated; id-only логи |

## Альтернативы

1. **GUARANTEE через generic POST /tickets оператором** — отклонено: ТЗ «системный триггер»; исключения детектирует upstream.
2. **INSURANCE через наш decide()** — отклонено: решение за страховщиком, не наш вердикт (D2).
3. **insurer-outbound read→None деградация** — отклонено: это мутация (ADR-0010 Реш.4 — raise, как bank).
4. **Uniq-индекс guarantee-reference сейчас** — отложено: hardening-follow-up при провижининге (прецедент M1).
5. **Отдельное действие фиксации регресса/передачи в страховую** — отклонено: лишний скоуп; регресс=ссылки, outbound=на переходе.

## Последствия

### Положительные
- GUARANTEE/INSURANCE реализованы под готовый домен (E10-1); всё config-gated/инертно до ops.
- Финмодель FR-9.8/D2 (регресс/пеня — ссылки), NFR-4.4 (мягкая деградация/never-raise), разделение «наш decide ≠ вердикт страховщика».

### Отрицательные / компромиссы
- Провизорные формы guarantee/insurer могут измениться → `# provisional contract`, локализация в схемах/адаптерах.
- Идемпотентность guarantee без индекса — держится на сериализации инертного режима; полный constraint — follow-up.

### Технические следствия
- Новый пакет `clients/insurer/` + `tickets/insurer_dispatch.py`; `webhooks/guarantee_inbound.py`; расширение `webhooks/inbound.py`;
  `is_insurance_submitted` в `case_state_machine.py`; `TicketRepository.find_guarantee_by_reference`.
- config: `guarantee_inbound_secret`, `insurer_api_base_url`/`insurer_api_token` (пусто=off).
- OpenAPI: `createGuaranteeEvent` + `GuaranteeEventIngest` (новая); `InsurerEventIngest` расширена → реген schema.d.ts + AT-002.
  insurer-outbound в openapi НЕ описывается. Миграций НЕТ.

## Ссылки

- ТЗ: §3.3.2/§3.3.3, §4.9 FR-9.5/9.6; Договор 5.7.5/5.7.6/5.7.7/5.7.8
- Связанные ADR: ADR-0013 (D2 пеня, D8 маршрутизация), ADR-0014 (insurer-outbound l.67), ADR-0016 (M1 отложенный constraint),
  ADR-0010 Реш.4 (мутация→raise), ADR-0005 (финмодель/двухконтурность)
- Issue: #200 (E10-10); follow-up #77 (m2m), #79 (durable); провижининг платёжного контура/страховщика
- Ревью плана #200: REQUEST-CHANGES→APPROVE-WITH-CONDITIONS (A1 идемпотентность, A2 раскладка, B1 эмит, C1б illegal-transition)
