"use client";

import { useState } from "react";

import {
  CHANNEL_LABELS,
  PRIORITY_LABELS,
  SORT_LABELS,
  STATUS_LABELS,
  TEAM_LABELS,
  TYPE_LABELS,
} from "./format";
import { updateField } from "./query";
import type { ListTicketsQuery } from "./types";

interface Props {
  value: ListTicketsQuery;
  onChange: (next: ListTicketsQuery) => void;
  disabled?: boolean;
}

const SELECTS: { key: keyof ListTicketsQuery; title: string; options: Record<string, string> }[] = [
  { key: "status", title: "Статус", options: STATUS_LABELS },
  { key: "type", title: "Тип", options: TYPE_LABELS },
  { key: "priority", title: "Приоритет", options: PRIORITY_LABELS },
  { key: "channel", title: "Канал", options: CHANNEL_LABELS },
  { key: "team", title: "Команда", options: TEAM_LABELS },
];

const TEXT_FILTERS: { key: keyof ListTicketsQuery; title: string; placeholder: string }[] = [
  { key: "assignee_id", title: "Исполнитель (uuid)", placeholder: "assignee_id" },
  { key: "requester_id", title: "Заявитель (uuid)", placeholder: "requester_id" },
  { key: "premises_id", title: "Объект (uuid)", placeholder: "premises_id" },
  { key: "tag", title: "Тег", placeholder: "тег" },
];

const fieldClass = "rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50";

export function TicketFilters({ value, onChange, disabled }: Props) {
  // Текстовые фильтры буферизуются локально и коммитятся на blur/Enter, чтобы не
  // дёргать router на каждый символ. Remount при смене фильтров пересеивает буфер.
  const [text, setText] = useState<Record<string, string>>(() => ({
    assignee_id: (value.assignee_id as string | undefined) ?? "",
    requester_id: (value.requester_id as string | undefined) ?? "",
    premises_id: (value.premises_id as string | undefined) ?? "",
    tag: value.tag ?? "",
  }));

  const select = (key: string, raw: string) => onChange(updateField(value, key, raw));
  const commitText = (key: string) => onChange(updateField(value, key, text[key]?.trim() ?? ""));

  const slaValue = value.sla_breached === undefined ? "" : String(value.sla_breached);

  return (
    <div className="flex flex-wrap items-end gap-3" aria-label="Фильтры">
      {SELECTS.map(({ key, title, options }) => (
        <label key={key} className="flex flex-col gap-1 text-xs text-gray-500">
          {title}
          <select
            className={fieldClass}
            disabled={disabled}
            value={(value[key] as string | undefined) ?? ""}
            onChange={(e) => select(key, e.target.value)}
          >
            <option value="">Все</option>
            {Object.entries(options).map(([val, lbl]) => (
              <option key={val} value={val}>
                {lbl}
              </option>
            ))}
          </select>
        </label>
      ))}

      <label className="flex flex-col gap-1 text-xs text-gray-500">
        SLA
        <select
          className={fieldClass}
          disabled={disabled}
          value={slaValue}
          onChange={(e) => select("sla_breached", e.target.value)}
        >
          <option value="">Все</option>
          <option value="true">Нарушен</option>
          <option value="false">В норме</option>
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Сортировка
        <select
          className={fieldClass}
          disabled={disabled}
          value={value.sort ?? ""}
          onChange={(e) => select("sort", e.target.value)}
        >
          <option value="">По умолчанию</option>
          {Object.entries(SORT_LABELS).map(([val, lbl]) => (
            <option key={val} value={val}>
              {lbl}
            </option>
          ))}
        </select>
      </label>

      {TEXT_FILTERS.map(({ key, title, placeholder }) => (
        <label key={key} className="flex flex-col gap-1 text-xs text-gray-500">
          {title}
          <input
            className={fieldClass}
            disabled={disabled}
            placeholder={placeholder}
            value={text[key] ?? ""}
            onChange={(e) => setText((prev) => ({ ...prev, [key]: e.target.value }))}
            onBlur={() => commitText(key)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commitText(key);
              }
            }}
          />
        </label>
      ))}
    </div>
  );
}
