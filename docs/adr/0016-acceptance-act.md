# ADR-0016: Поток ACCEPTANCE_ACT — signing_status, блокировка, каскад (E10-9)

## Статус

- [ ] Предложено
- [x] **Принято** — *ожидает подписи Архитектора*
- **Дата:** 2026-06-10
- **Автор:** Агент-Разработчик; принимается Архитектором (Evgeniy)
- **Согласовано Архитектором:** 4 решения зафиксированы 2026-06-10 (signing-резолв+OTP, мягкая блокировка, авто-каскад, новая операция); подпись «Принято» — при merge.

> Этот ADR детализирует **ADR-0013 Решение 9** (каскад MOVE_OUT→COMPENSATION, оставленный «на E10-9»)
> и уточняет **ADR-0014** (провизорный контракт `AcceptanceAct`, U4 PaymentReleaseChecker) для под-задачи
> **E10-9 (#199)**: акт приёмки-передачи (FR-9.7, §3.3.4). Прецедент провизорных контрактов — ADR-0006/0015.
> Боевые контракты — при провижининге; до тех пор всё **config-gated и инертно** (#77/#79/#161).

## Контекст

Домен ACCEPTANCE_ACT есть с E10-1: `ActKind`(MOVE_IN/MOVE_OUT), `SigningStatus`(one_signed/both_signed/
disputed), `TicketCaseDetails.act_kind/signing_status` (typed top-level, D4), `Ticket.acceptance_act_id`,
`AcceptanceActPayload.blocked_payment_id`. **В коде НЕТ:** AcceptanceAct-клиента, понятия «ущерб», поля
линка каскада, гейта по подписи, операции приёма акта (в openapi её нет).

**ТЗ §3.3.4 / FR-9.7:** акт двусторонне подписывается по **SMS-OTP**; до подписания обеими сторонами
блокируется выплата (MOVE_IN — первая выплата наймодателю, MOVE_OUT — возврат обеспечительного); при
ущербе на выезде фиксируются расхождения и создаётся связанный COMPENSATION. **Подписание (SMS-OTP) —
upstream**; kb-support не генерирует/не валидирует OTP, только резолвит `signing_status` по сети и доводит.

**Инвариант финмодели (FR-9.8):** kb-support хранит решение/ссылки, деньги не считает. **NFR-4.4:** сбой
соседа не ломает lifecycle. **ФЗ-152:** ПДн/OTP не в логах.

## Решение

**D1 — `signing_status` = резолв через AcceptanceAct read-клиент + операторская переотправка OTP.**
Новый `clients/acceptance_act/` (`GET /api/v1/acts/{acceptance_act_id}` → `{id, kind, signing_status,
damage_amount?}`, **мягкая деградация → None + WARN**, config-gated по `acceptance_act_api_token`, эталон
`payment_checker`). kb-support **резолвит** `signing_status` и сохраняет в `TicketCaseDetails.signing_status`.
SMS-OTP-подписание — upstream; kb-support лишь **триггерит переотправку** OTP через sms-seam (#161, инертно).
**OTP-код НИКОГДА не логируется и не хранится** в kb-support.

**D2 — Блокировка выплаты/возврата = МЯГКАЯ (через PaymentReleaseChecker, БЕЗ hard-gate).**
> **Отступление от буквы issue #199 (CLAUDE.md правило 11, решение Архитектора 2026-06-10).** Issue говорит
> «блокировка выплаты»; реализуем **мягко**: kb-support **хранит** `signing_status`/`blocked_payment_id`
> (ссылка-флаг для оператора, **не enforced-гейт**), а разблокировку выплаты проверяет upstream
> `PaymentReleaseChecker` (ADR-0014 U4, информационно). Жёсткий гейт PAID по `signing_status` **НЕ вводится** —
> он связал бы детерминированный case_state с доступностью соседа (нарушение NFR-4.4). Согласовано: U4.

**D3 — Каскад MOVE_OUT + ущерб → связанный COMPENSATION = авто из upstream-резолва.**
`damage_amount` приходит из AcceptanceAct-резолва (НЕ операторский ввод). При `act_kind=MOVE_OUT` +
`damage_amount>0` системно создаётся связанный COMPENSATION (системный актор `CLAIMS_ACTOR_ID` —
новый sentinel-UUID в `auth/system_actors.py`, паттерн AUTOMATION/EMAIL_SENDER). Создание — через
`TicketRepository.create` (проходит `apply_claim_intake`: `case_state=CLAIM_SUBMITTED`, флаги D10 >50k→
independent_appraisal). `claim_amount = damage_amount` — **как ССЫЛКА/перенос значения из акта, без
арифметики** (FR-9.8). `requester_id` наследуется, `channel=SYSTEM`, маршрутизация → finance (AutomationRule, D8).
Линк **двусторонний в payload** (родитель `linked_compensation_ticket_id` ↔ ребёнок `source_acceptance_ticket_id`),
**без миграции** (D4/ADR-0014 паттерн).

**D4 — Новая операция `POST /tickets/{id}/acceptance-act`.**
Оператор фиксирует `act_kind` + `acceptance_act_id` → операция (а) проставляет `Ticket.acceptance_act_id` +
`TicketCaseDetails.act_kind`, (б) резолвит `signing_status` через клиент (config-gated), (в) триггерит OTP-resend
seam, (г) при MOVE_OUT+damage — каскад (D3). **RBAC = оператор-гейт** (`_require_operator`; ACCEPTANCE_ACT→support
по D8, НЕ legal/finance как `decide`). Только claims-заявка с `case_state` (иначе 422), 404 anti-enum. Провизорно
добавляется в `docs/openapi.yaml` (операция `recordAcceptanceAct` + схема `AcceptanceActInput`) + AT-002 + реген
schema.d.ts. Каждое значимое изменение — строка `TicketHistory` (actor=оператор/CLAIMS_ACTOR_ID для каскада).

**Авторитетность `signing_status` (M4).** **Upstream-резолв (акт) авторитетен.** Операторский ввод его не
перетирает вслепую; при выключенной интеграции (резолв→None) колонка НЕ затирается в NULL. Резолв
**идемпотентен** (тот же акт → no-op, без лишней записи в журнал — паттерн `inbound.py`/`transition_case_state`).

**Идемпотентность каскада (M1).** Guard детерминированный: перед созданием COMPENSATION проверяется
существующий `linked_compensation_ticket_id` в payload родителя (в той же транзакции, эталон
`_record_regress_due_at`). Под текущим **config-gated/инертным** режимом резолв операторо-триггерный
(сериализован на тикет) — конкурентный двойной резолв одного акта маловероятен; **БД-инвариант
(частичный uniq на пару родитель→ребёнок) — hardening-follow-up при провижининге боевой интеграции**
(когда резолв может прийти асинхронно/durable, #79).

### Провизорные контракты (уточняются при провижининге)

| Направление | Операция (provisional) | Семантика | Безопасность / деградация |
|---|---|---|---|
| Outbound (нам→AcceptanceAct) | `GET /api/v1/acts/{id}` → `{id, kind, signing_status, damage_amount?}` | резолв статуса акта + ущерба (D1/D3) | read → None + WARN (мягко, ADR-0014); config-gated; ПДн/тело не в логах |
| Внутр. (оператор→нам) | `POST /api/v1/support/tickets/{id}/acceptance-act` `{act_kind, acceptance_act_id}` → Ticket | фиксация акта + резолв + OTP-resend + каскад (D4) | оператор-гейт; 422 не-claims; 404 anti-enum |
| Seam (нам→sms) | OTP-resend поверх sms-канала (#161) | переотправка OTP стороне | config-gated (пустой sms-токен=off); **OTP не логируется** |

## Альтернативы

1. **Жёсткий гейт PAID по signing_status** — отклонено (D2/U4): связывает state-machine с доступностью соседа (NFR-4.4).
2. **SMS-OTP-подписание в kb-support** — отклонено: подписи живут upstream (§3.3.4); инфры OTP в kb-support нет.
3. **Каскад по операторскому вводу ущерба** — отклонено Архитектором в пользу авто-резолва из акта (D3).
4. **Линк каскада новой колонкой на Ticket** — отклонено: линк в payload без миграции (D3/D4-паттерн).
5. **Без новой операции (всё через upstream-резолв)** — отклонено Архитектором: оператору нужен явный ввод акта (§3.3.4).

## Последствия

### Положительные
- Поток акта реализуется под существующий домен (E10-1) без слома; всё config-gated/инертно до ops.
- NFR-4.4 сохранён (мягкая блокировка, мягкая деградация клиента); финмодель FR-9.8 (claim_amount=ссылка).
- Каскад замкнут: резолв ущерба → системный COMPENSATION с двусторонним линком.

### Отрицательные / компромиссы
- Провизорный формат акта (`damage_amount` в ответе) может измениться → локализуется в адаптере (`# provisional`).
- Мягкая блокировка: kb-support не enforce'ит подпись перед выплатой (полагается на upstream PaymentReleaseChecker).
- Идемпотентность каскада под боевой асинхронной интеграцией требует БД-инварианта (follow-up при провижининге).

### Технические следствия
- Новый пакет `clients/acceptance_act/` + config `acceptance_act_api_base_url`/`_token` (пусто=off, TODO #77).
- `tickets/acceptance.py` (операция/резолв/OTP-seam) + `tickets/acceptance_cascade.py` (каскад); `case_repository`
  +метод обновления signing_status; `auth/system_actors.CLAIMS_ACTOR_ID`.
- OpenAPI: `recordAcceptanceAct` + `AcceptanceActInput` (провизорно) + реген `frontend/lib/api/schema.d.ts` + AT-002.
- Миграций НЕТ (линк в payload; домен/колонки с E10-1).

## Ссылки

- ТЗ: §3.3.4, §3.3.1, §4.9 FR-9.7; Договор найма 5.7/5.8
- Связанные ADR: ADR-0013 (D9 каскад, D4 размещение, D8 маршрутизация), ADR-0014 (AcceptanceAct контракт, U4),
  ADR-0006/0015 (прецедент провизорных контрактов), ADR-0005 (финмодель/двухконтурность)
- Issue: #199 (E10-9); follow-up #77 (m2m), #161 (sms-доставка/OTP), #79 (durable)
- Ревью плана #199: APPROVE-WITH-CONDITIONS (M1 гонка каскада, M2 мягкая блокировка, M3 контракт операции,
  M4 авторитетность signing_status; C1–C16)
