"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { ReportType } from "@/lib/api/client";

import { downloadReportCsvAction } from "./actions";
import { REPORT_TYPE_LABELS, REPORT_TYPES } from "./types";

/**
 * Управление отчётом (#171): тип + период (URL-driven, как #170) + скачивание CSV.
 * «Показать» правит URL → Server Component перечитывает и тянет отчёт серверно.
 * CSV: server action (токен на сервере) отдаёт строку, клиент формирует Blob —
 * токен в браузер не уходит. Пустые from/to не идут в URL → дефолт бэкенда (30 дней).
 */
const fieldClass = "rounded border border-gray-300 px-2 py-1 text-sm";

export function ReportControls({
  type,
  from,
  to,
}: {
  type: ReportType;
  from?: string;
  to?: string;
}) {
  const router = useRouter();
  const [typeValue, setTypeValue] = useState<ReportType>(type);
  const [fromValue, setFromValue] = useState(from ?? "");
  const [toValue, setToValue] = useState(to ?? "");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildQs = () => {
    const params = new URLSearchParams();
    params.set("type", typeValue);
    if (fromValue.trim()) params.set("from", fromValue.trim());
    if (toValue.trim()) params.set("to", toValue.trim());
    return params.toString();
  };

  const show = () => router.push(`/reports?${buildQs()}`);

  const download = async () => {
    setPending(true);
    setError(null);
    try {
      const result = await downloadReportCsvAction(
        typeValue,
        fromValue.trim() || undefined,
        toValue.trim() || undefined,
      );
      if ("error" in result) {
        setError(result.error);
        return;
      }
      const blob = new Blob([result.csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = result.filename;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <form
        className="flex flex-wrap items-end gap-3"
        aria-label="Параметры отчёта"
        onSubmit={(e) => {
          e.preventDefault();
          show();
        }}
      >
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Отчёт
          <select
            className={fieldClass}
            value={typeValue}
            onChange={(e) => setTypeValue(e.target.value as ReportType)}
          >
            {REPORT_TYPES.map((t) => (
              <option key={t} value={t}>
                {REPORT_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          С
          <input
            type="date"
            className={fieldClass}
            value={fromValue}
            onChange={(e) => setFromValue(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          По
          <input
            type="date"
            className={fieldClass}
            value={toValue}
            onChange={(e) => setToValue(e.target.value)}
          />
        </label>
        <button
          type="submit"
          className="rounded bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700"
        >
          Показать
        </button>
        <button
          type="button"
          className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          onClick={download}
          disabled={pending}
        >
          {pending ? "Готовим CSV…" : "Скачать CSV"}
        </button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
