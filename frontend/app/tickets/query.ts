import type { ListTicketsQuery } from "./types";

// sort-значения из контракта (operations.listTickets.parameters.query.sort).
export const SORT_VALUES = [
  "created_at",
  "-created_at",
  "resolution_due_at",
  "-resolution_due_at",
  "priority",
  "-priority",
] as const;
type Sort = (typeof SORT_VALUES)[number];

// Строковые фильтры, прокидываемые на бэкенд как есть (валидацию значений делает
// сервис; фронт scope/видимость не вычисляет — ADR-0003).
const STRING_KEYS = [
  "status",
  "type",
  "priority",
  "channel",
  "team",
  "assignee_id",
  "requester_id",
  "premises_id",
  "tag",
] as const;

type SearchParams = Record<string, string | string[] | undefined>;

const first = (v: string | string[] | undefined): string | undefined =>
  Array.isArray(v) ? v[0] : v;

/** Разбирает searchParams URL в типизированный запрос списка (cursor не из URL). */
export function parseQuery(sp: SearchParams): ListTicketsQuery {
  // Сборка по динамическим ключам; форма соответствует ListTicketsQuery — один cast.
  const q: Record<string, string | boolean> = {};
  for (const key of STRING_KEYS) {
    const val = first(sp[key]);
    if (val) q[key] = val;
  }
  const sort = first(sp.sort);
  if (sort && (SORT_VALUES as readonly string[]).includes(sort)) {
    q.sort = sort;
  }
  const breached = first(sp.sla_breached);
  if (breached === "true") q.sla_breached = true;
  else if (breached === "false") q.sla_breached = false;
  return q as ListTicketsQuery;
}

/** Сериализует запрос в query-строку для router (пустые/undefined отбрасываются). */
export function toSearchString(query: ListTicketsQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

/**
 * Стабильный ключ набора фильтров (без cursor/limit) — для React-remount при
 * смене фильтров и отбрасывания устаревшего ответа «load more».
 */
export function queryKey(query: ListTicketsQuery): string {
  const entries = Object.entries(query)
    .filter(([key]) => key !== "cursor" && key !== "limit")
    .sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify(entries);
}

/** Чистое обновление одного поля фильтра. Пустая строка → удаление поля. */
export function updateField(query: ListTicketsQuery, key: string, raw: string): ListTicketsQuery {
  const next: Record<string, unknown> = { ...query };
  if (raw === "") {
    delete next[key];
  } else if (key === "sla_breached") {
    next[key] = raw === "true";
  } else {
    next[key] = raw;
  }
  // Пагинация сбрасывается при любой смене фильтра.
  delete next.cursor;
  return next as ListTicketsQuery;
}

export type { Sort };
