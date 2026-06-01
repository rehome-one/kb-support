"use client";

import { useState } from "react";

import type { MessageCreateInput } from "@/lib/api/client";

import type { ActionResult } from "./types";

interface Props {
  ticketId: string;
  createMessageAction: (id: string, input: MessageCreateInput) => Promise<ActionResult>;
}

export function MessageComposer({ ticketId, createMessageAction }: Props) {
  const [body, setBody] = useState("");
  const [isInternal, setIsInternal] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ status: number; title: string } | null>(null);

  async function submit() {
    const text = body.trim();
    if (!text || pending) return;
    setPending(true);
    setError(null);
    // is_internal лишь передаётся флагом — видимость/RBAC (403 не-оператору) решает бэкенд (NFR-1.3).
    const result = await createMessageAction(ticketId, { body: text, is_internal: isInternal });
    setPending(false);
    if (result.ok) {
      // Очистка строго по успеху (revalidatePath обновит переписку).
      setBody("");
      setIsInternal(false);
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
