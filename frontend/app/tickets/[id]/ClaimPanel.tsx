import {
  ACT_KIND_LABELS,
  CASE_STATE_LABELS,
  DECISION_LABELS,
  SIGNING_STATUS_LABELS,
  TYPE_LABELS,
  formatDateTime,
  formatMoney,
  formatScalar,
  label,
  shortId,
} from "../format";
import type { Ticket, TicketCaseDetails } from "./types";

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-gray-500">{title}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

// Детали кейса (case_type/act_kind/signing_status + opaque payload). payload — свободный
// объект контракта (additionalProperties): рендерим строго нейтрально, без доменной
// интерпретации (иначе дрейф при изменении claims-схем).
function CaseDetails({ details }: { details: TicketCaseDetails }) {
  const payloadEntries = Object.entries(details.payload ?? {});
  return (
    <div className="flex flex-col gap-2 border-t pt-3">
      <h3 className="text-xs font-medium text-gray-500">Детали разбирательства</h3>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Field title="Тип кейса">{label(TYPE_LABELS, details.case_type)}</Field>
        {details.act_kind ? (
          <Field title="Вид акта">{label(ACT_KIND_LABELS, details.act_kind)}</Field>
        ) : null}
        {details.signing_status ? (
          <Field title="Статус подписания">
            {label(SIGNING_STATUS_LABELS, details.signing_status)}
          </Field>
        ) : null}
      </dl>
      {payloadEntries.length > 0 ? (
        <dl className="flex flex-col gap-1">
          {payloadEntries.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-sm">
              <dt className="font-mono text-xs text-gray-500">{key}</dt>
              <dd className="font-mono text-xs text-gray-700">{formatScalar(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

// Read-only секция претензионной заявки (E10, #201). Рендерится страницей только для
// claims-типов; токен/данные — на сервере (server component, ПДн не в клиентский бандл).
export function ClaimPanel({ ticket }: { ticket: Ticket }) {
  return (
    <section
      className="flex flex-col gap-4 rounded border border-gray-200 p-4"
      aria-label="Претензионное разбирательство"
    >
      <h2 className="text-lg font-semibold">Претензия</h2>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Field title="Состояние">{label(CASE_STATE_LABELS, ticket.case_state)}</Field>
        <Field title="Сумма претензии">{formatMoney(ticket.claim_amount)}</Field>
        <Field title="Одобренная сумма">{formatMoney(ticket.approved_amount)}</Field>
      </dl>

      {/* Решение по претензии (decide(), FR-9.6). Read-only — форма в ClaimActions. */}
      <div className="flex flex-col gap-2 border-t pt-3">
        <h3 className="text-xs font-medium text-gray-500">Решение</h3>
        {ticket.decision == null ? (
          <p className="text-sm text-gray-400">решение ещё не принято</p>
        ) : (
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Field title="Вердикт">{label(DECISION_LABELS, ticket.decision)}</Field>
            <Field title="Уведомлено">{formatDateTime(ticket.decision_notified_at)}</Field>
            {ticket.decision_reason ? (
              <div className="col-span-full flex flex-col gap-0.5">
                <dt className="text-xs text-gray-500">Мотивировка</dt>
                <dd className="whitespace-pre-wrap text-sm">{ticket.decision_reason}</dd>
              </div>
            ) : null}
          </dl>
        )}
      </div>

      {/* Аудит выплаты (§8.1: kb-support хранит решение и ссылки, деньги считает
          платёжный контур; реальная выплата — config-gated до #79). */}
      <div className="flex flex-col gap-2 border-t pt-3">
        <h3 className="text-xs font-medium text-gray-500">Выплата</h3>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Field title="Срок выплаты">{formatDateTime(ticket.payout_due_at)}</Field>
          <Field title="Платёж">
            {ticket.linked_payment_id ? (
              <span className="font-mono text-gray-600" title={ticket.linked_payment_id}>
                {shortId(ticket.linked_payment_id)}
              </span>
            ) : (
              <span className="text-gray-400">ожидается</span>
            )}
          </Field>
        </dl>
      </div>

      {ticket.case_details ? <CaseDetails details={ticket.case_details} /> : null}
    </section>
  );
}
