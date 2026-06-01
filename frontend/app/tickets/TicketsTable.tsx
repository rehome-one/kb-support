import Link from "next/link";

import {
  PRIORITY_LABELS,
  STATUS_LABELS,
  TEAM_LABELS,
  TYPE_LABELS,
  formatDateTime,
  label,
  shortId,
} from "./format";
import type { TicketSummary } from "./types";

const COLUMNS = [
  "Номер",
  "Тема",
  "Статус",
  "Приоритет",
  "Тип",
  "Исполнитель",
  "Команда",
  "Создана",
  "SLA",
] as const;

// Весь user-content (number/subject/tags) — текстовые ноды React (без
// dangerouslySetInnerHTML): защита от XSS по умолчанию.
export function TicketsTable({ rows }: { rows: TicketSummary[] }) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b text-left text-gray-500">
          {COLUMNS.map((col) => (
            <th key={col} scope="col" className="py-2 pr-3 font-medium">
              {col}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((ticket) => (
          <tr key={ticket.id} className="border-b last:border-0 hover:bg-gray-50">
            <td className="py-2 pr-3 font-mono">
              <Link href={`/tickets/${ticket.id}`} className="text-blue-700 hover:underline">
                {ticket.number}
              </Link>
            </td>
            <td className="py-2 pr-3">{ticket.subject}</td>
            <td className="py-2 pr-3">{label(STATUS_LABELS, ticket.status)}</td>
            <td className="py-2 pr-3">{label(PRIORITY_LABELS, ticket.priority)}</td>
            <td className="py-2 pr-3">{label(TYPE_LABELS, ticket.type)}</td>
            <td
              className="py-2 pr-3 font-mono text-gray-600"
              title={ticket.assignee_id ?? undefined}
            >
              {shortId(ticket.assignee_id)}
            </td>
            <td className="py-2 pr-3">{label(TEAM_LABELS, ticket.team)}</td>
            <td className="py-2 pr-3 whitespace-nowrap text-gray-600">
              {formatDateTime(ticket.created_at)}
            </td>
            <td className="py-2 pr-3">
              {ticket.sla_breached ? (
                <span role="status" aria-label="SLA нарушен" className="font-medium text-red-600">
                  ● SLA
                </span>
              ) : (
                <span className="text-gray-300" aria-hidden="true">
                  —
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
