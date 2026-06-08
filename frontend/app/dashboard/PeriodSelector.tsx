"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Выбор периода панели (#170). URL-driven: коммитит `from`/`to` в query, страница
 * (Server Component) перечитывает и заново тянет статистику серверно. Пустые поля
 * НЕ попадают в URL → срабатывает дефолт бэкенда (30 дней, #165), а не `from=`.
 */
const fieldClass = "rounded border border-gray-300 px-2 py-1 text-sm";

export function PeriodSelector({ from, to }: { from?: string; to?: string }) {
  const router = useRouter();
  const [fromValue, setFromValue] = useState(from ?? "");
  const [toValue, setToValue] = useState(to ?? "");

  const apply = () => {
    const params = new URLSearchParams();
    if (fromValue.trim()) params.set("from", fromValue.trim());
    if (toValue.trim()) params.set("to", toValue.trim());
    const qs = params.toString();
    router.push(qs ? `/dashboard?${qs}` : "/dashboard");
  };

  const reset = () => {
    setFromValue("");
    setToValue("");
    router.push("/dashboard");
  };

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      aria-label="Период"
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
    >
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
        Применить
      </button>
      <button
        type="button"
        className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
        onClick={reset}
      >
        Сбросить
      </button>
    </form>
  );
}
