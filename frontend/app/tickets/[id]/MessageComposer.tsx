"use client";

import { useState } from "react";

import type { MessageCreateInput } from "@/lib/api/client";

import type { ActionResult, CannedSummary, RenderResult } from "./types";

interface Props {
  ticketId: string;
  createMessageAction: (id: string, input: MessageCreateInput) => Promise<ActionResult>;
  templates: CannedSummary[];
  renderTemplateAction: (ticketId: string, cannedId: string) => Promise<RenderResult>;
}

export function MessageComposer({
  ticketId,
  createMessageAction,
  templates,
  renderTemplateAction,
}: Props) {
  const [body, setBody] = useState("");
  const [isInternal, setIsInternal] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ status: number; title: string } | null>(null);
  // Шаблон-источник вставленного текста — для учёта usage_count (#128). Сбрасывается
  // после отправки; ручная правка текста его НЕ сбрасывает (шаблон всё равно использован).
  const [cannedId, setCannedId] = useState<string | null>(null);

  async function insertTemplate(id: string) {
    if (!id || pending) return;
    setPending(true);
    setError(null);
    const result = await renderTemplateAction(ticketId, id);
    setPending(false);
    if (result.ok) {
      setBody(result.body);
      setCannedId(id);
    } else {
      setError({ status: result.status, title: result.title });
    }
  }

  async function submit() {
    const text = body.trim();
    if (!text || pending) return;
    setPending(true);
    setError(null);
    // is_internal лишь передаётся флагом — видимость/RBAC (403 не-оператору) решает бэкенд (NFR-1.3).
    // canned_response_id — для usage_count (#128); бэкенд best-effort, отсутствие не валит отправку.
    const result = await createMessageAction(ticketId, {
      body: text,
      is_internal: isInternal,
      ...(cannedId ? { canned_response_id: cannedId } : {}),
    });
    setPending(false);
    if (result.ok) {
      // Очистка строго по успеху (revalidatePath обновит переписку).
      setBody("");
      setIsInternal(false);
      setCannedId(null);
    } else {
      setError({ status: result.status, title: result.title });
    }
  }

  return (
    <form
      className="flex flex-col gap-2 rounded border border-gray-200 p-3"
      aria-label="Новое сообщение"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error.title}
        </div>
      )}

      {templates.length > 0 && (
        <label className="flex items-center gap-2 text-sm">
          <span className="text-gray-600">Шаблон:</span>
          <select
            className="rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50"
            aria-label="Вставить шаблон ответа"
            disabled={pending}
            value=""
            onChange={(e) => insertTemplate(e.target.value)}
          >
            <option value="">— выбрать —</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
        </label>
      )}

      <textarea
        className="min-h-20 rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50"
        placeholder="Ответ заявителю…"
        aria-label="Текст сообщения"
        disabled={pending}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          disabled={pending}
          checked={isInternal}
          onChange={(e) => setIsInternal(e.target.checked)}
        />
        Внутренняя заметка
      </label>

      {isInternal && (
        <p role="note" className="text-xs font-medium text-amber-700">
          Не видно заявителю — только операторам.
        </p>
      )}

      <div className="flex items-center justify-between">
        <button
          type="button"
          className="cursor-not-allowed text-xs text-gray-400"
          disabled
          title="Вложения появятся в E7 (kb-files)"
        >
          + Вложение (позже)
        </button>
        <button
          type="submit"
          className="rounded bg-gray-900 px-4 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
          disabled={pending || !body.trim()}
        >
          {isInternal ? "Добавить заметку" : "Отправить ответ"}
        </button>
      </div>
    </form>
  );
}
