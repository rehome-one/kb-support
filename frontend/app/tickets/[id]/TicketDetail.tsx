import {
  CHANNEL_LABELS,
  PRIORITY_LABELS,
  STATUS_LABELS,
  TEAM_LABELS,
  TYPE_LABELS,
  formatDateTime,
  label,
  shortId,
} from "../format";
import { SlaBadge } from "../SlaBadge";
import type { Ticket } from "./types";

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-gray-500">{title}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

export function TicketDetail({ ticket }: { ticket: Ticket }) {
  return (
    <section className="flex flex-col gap-4 rounded border border-gray-200 p-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-gray-500">{ticket.number}</span>
        <h1 className="text-xl font-semibold">{ticket.subject}</h1>
      </header>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Field title="Статус">{label(STATUS_LABELS, ticket.status)}</Field>
        <Field title="Приоритет">{label(PRIORITY_LABELS, ticket.priority)}</Field>
        <Field title="Тип">{label(TYPE_LABELS, ticket.type)}</Field>
        <Field title="Канал">{label(CHANNEL_LABELS, ticket.channel)}</Field>
        <Field title="Команда">{label(TEAM_LABELS, ticket.team)}</Field>
        <Field title="Исполнитель">
          <span className="font-mono text-gray-600" title={ticket.assignee_id ?? undefined}>
            {shortId(ticket.assignee_id)}
          </span>
        </Field>
        <Field title="Создана">{formatDateTime(ticket.created_at)}</Field>
        <Field title="Обновлена">{formatDateTime(ticket.updated_at)}</Field>
        <Field title="Срок решения">{formatDateTime(ticket.resolution_due_at)}</Field>
        <Field title="SLA">
          <SlaBadge state={ticket.sla_state} />
        </Field>
      </dl>

      {ticket.description ? (
        <div className="flex flex-col gap-1">
          <h2 className="text-xs text-gray-500">Описание</h2>
          <p className="whitespace-pre-wrap text-sm">{ticket.description}</p>
        </div>
      ) : null}

      {/* Оценка качества (FR-8.1, #185): read-only. Оценку ставит заявитель в ЛК (ADR-0012 D1). */}
      <div className="flex flex-col gap-1">
        <h2 className="text-xs text-gray-500">Оценка качества</h2>
        {ticket.rating == null ? (
          <p className="text-sm text-gray-400">не оценена</p>
        ) : (
          <>
            <p className="text-sm">{`${ticket.rating} / 5`}</p>
            {ticket.rating_comment ? (
              <p className="whitespace-pre-wrap text-sm text-gray-700">{ticket.rating_comment}</p>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
