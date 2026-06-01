"use client";

import { useState } from "react";

import type {
  AssignInput,
  EscalateInput,
  ReopenInput,
  ResolveInput,
  TicketUpdateInput,
} from "@/lib/api/client";

import { PRIORITY_LABELS, STATUS_LABELS, TEAM_LABELS, label } from "../format";
import type { ActionResult, Ticket } from "./types";

interface Props {
  ticket: Ticket;
  patchAction: (id: string, patch: TicketUpdateInput) => Promise<ActionResult>;
  assignAction: (id: string, input: AssignInput) => Promise<ActionResult>;
  escalateAction: (id: string, input: EscalateInput) => Promise<ActionResult>;
  resolveAction: (id: string, input: ResolveInput) => Promise<ActionResult>;
  closeAction: (id: string) => Promise<ActionResult>;
  reopenAction: (id: string, input: ReopenInput) => Promise<ActionResult>;
}

const fieldClass = "rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50";

export function TicketActions({
  ticket,
  patchAction,
  assignAction,
  escalateAction,
  resolveAction,
  closeAction,
  reopenAction,
}: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ status: number; title: string } | null>(null);
  const [openForm, setOpenForm] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);

  // Поле optional в типах — безопасно деградируем к пустому списку.
  const allowed = ticket.allowed_status_transitions ?? [];
  const statusOptions = [ticket.status, ...allowed];
  const [tagsText, setTagsText] = useState((ticket.tags ?? []).join(", "));

  // Единая точка запуска мутации: pending + сброс ошибки + обработка результата.
  async function dispatch(run: () => Promise<ActionResult>, onSuccess?: () => void) {
    setPending(true);
    setError(null);
    const result = await run();
    setPending(false);
    if (result.ok) {
      onSuccess?.();
    } else {
      setError({ status: result.status, title: result.title });
    }
  }

  const toggle = (name: string) => {
    setError(null);
    setOpenForm((cur) => (cur === name ? null : name));
    setConfirmClose(false);
  };

  return (
    <section
      className="flex flex-col gap-4 rounded border border-gray-200 p-4"
      aria-label="Управление заявкой"
    >
      <h2 className="text-lg font-semibold">Управление</h2>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error.title}
        </div>
      )}

      {/* --- PATCH: статус / приоритет / команда --- */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Статус
          <select
            className={fieldClass}
            disabled={pending}
            value={ticket.status}
            onChange={(e) => {
              const next = e.target.value;
              if (next !== ticket.status)
                dispatch(() => patchAction(ticket.id, { status: next as Ticket["status"] }));
            }}
          >
            {statusOptions.map((s) => (
              <option key={s} value={s}>
                {label(STATUS_LABELS, s)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Приоритет
          <select
            className={fieldClass}
            disabled={pending}
            value={ticket.priority}
            onChange={(e) => {
              const next = e.target.value;
              if (next !== ticket.priority)
                dispatch(() => patchAction(ticket.id, { priority: next as Ticket["priority"] }));
            }}
          >
            {Object.keys(PRIORITY_LABELS).map((p) => (
              <option key={p} value={p}>
                {label(PRIORITY_LABELS, p)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Команда
          <select
            className={fieldClass}
            disabled={pending}
            value={ticket.team ?? ""}
            onChange={(e) => {
              const next = e.target.value;
              if (next && next !== ticket.team)
                dispatch(() =>
                  patchAction(ticket.id, { team: next as NonNullable<Ticket["team"]> }),
                );
            }}
          >
            {!ticket.team && <option value="">—</option>}
            {Object.keys(TEAM_LABELS).map((t) => (
              <option key={t} value={t}>
                {label(TEAM_LABELS, t)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* --- PATCH: теги (массив целиком) --- */}
      <div className="flex items-end gap-2">
        <label className="flex flex-1 flex-col gap-1 text-xs text-gray-500">
          Метки (через запятую)
          <input
            className={fieldClass}
            disabled={pending}
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50"
          disabled={pending}
          onClick={() => {
            const tags = tagsText
              .split(",")
              .map((t) => t.trim())
              .filter(Boolean);
            dispatch(() => patchAction(ticket.id, { tags }));
          }}
        >
          Сохранить метки
        </button>
      </div>

      {/* --- Действия --- */}
      <div className="flex flex-col gap-2 border-t pt-3">
        <div className="flex flex-wrap gap-2">
          {(["assign", "escalate", "resolve", "reopen"] as const).map((name) => (
            <button
              key={name}
              type="button"
              className="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50"
              disabled={pending}
              onClick={() => toggle(name)}
            >
              {ACTION_LABELS[name]}
            </button>
          ))}
          {/* close — двухшаговое подтверждение */}
          {!confirmClose ? (
            <button
              type="button"
              className="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50 disabled:opacity-50"
              disabled={pending}
              onClick={() => {
                setOpenForm(null);
                setError(null);
                setConfirmClose(true);
              }}
            >
              Закрыть
            </button>
          ) : (
            <span className="flex items-center gap-2">
              <span className="text-sm text-gray-600">Подтвердить закрытие?</span>
              <button
                type="button"
                className="rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700 disabled:opacity-50"
                disabled={pending}
                onClick={() =>
                  dispatch(
                    () => closeAction(ticket.id),
                    () => setConfirmClose(false),
                  )
                }
              >
                Подтвердить
              </button>
              <button
                type="button"
                className="text-sm text-gray-500 underline"
                disabled={pending}
                onClick={() => setConfirmClose(false)}
              >
                Отмена
              </button>
            </span>
          )}
        </div>

        {openForm === "assign" && (
          <AssignForm
            pending={pending}
            onSubmit={(input) =>
              dispatch(
                () => assignAction(ticket.id, input),
                () => setOpenForm(null),
              )
            }
          />
        )}
        {openForm === "escalate" && (
          <ReasonTeamForm
            pending={pending}
            submitLabel="Эскалировать на 2-ю линию"
            onSubmit={(input) =>
              dispatch(
                () => escalateAction(ticket.id, input),
                () => setOpenForm(null),
              )
            }
          />
        )}
        {openForm === "resolve" && (
          <NoteForm
            pending={pending}
            fieldLabel="Решение (необязательно)"
            submitLabel="Отметить решённой"
            onSubmit={(note) =>
              dispatch(
                () => resolveAction(ticket.id, { resolution_note: note }),
                () => setOpenForm(null),
              )
            }
          />
        )}
        {openForm === "reopen" && (
          <NoteForm
            pending={pending}
            fieldLabel="Причина переоткрытия (необязательно)"
            submitLabel="Переоткрыть заявку"
            onSubmit={(reason) =>
              dispatch(
                () => reopenAction(ticket.id, { reason }),
                () => setOpenForm(null),
              )
            }
          />
        )}
      </div>
    </section>
  );
}

const ACTION_LABELS: Record<string, string> = {
  assign: "Назначить",
  escalate: "Эскалировать",
  resolve: "Решить",
  reopen: "Переоткрыть",
};

function AssignForm({
  pending,
  onSubmit,
}: {
  pending: boolean;
  onSubmit: (input: AssignInput) => void;
}) {
  const [assigneeId, setAssigneeId] = useState("");
  const [team, setTeam] = useState("");
  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded bg-gray-50 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        const input: AssignInput = team
          ? { assignee_id: assigneeId, team: team as NonNullable<AssignInput["team"]> }
          : { assignee_id: assigneeId };
        onSubmit(input);
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Исполнитель (uuid)
        <input
          required
          className={fieldClass}
          value={assigneeId}
          onChange={(e) => setAssigneeId(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Команда (необязательно)
        <select className={fieldClass} value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">—</option>
          {Object.keys(TEAM_LABELS).map((t) => (
            <option key={t} value={t}>
              {label(TEAM_LABELS, t)}
            </option>
          ))}
        </select>
      </label>
      <button
        type="submit"
        className="rounded bg-gray-900 px-3 py-1 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        disabled={pending || !assigneeId.trim()}
      >
        Назначить исполнителя
      </button>
    </form>
  );
}

function ReasonTeamForm({
  pending,
  submitLabel,
  onSubmit,
}: {
  pending: boolean;
  submitLabel: string;
  onSubmit: (input: EscalateInput) => void;
}) {
  const [team, setTeam] = useState("");
  const [reason, setReason] = useState("");
  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded bg-gray-50 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        const input: EscalateInput = {};
        if (team) input.team = team as NonNullable<EscalateInput["team"]>;
        if (reason.trim()) input.reason = reason.trim();
        onSubmit(input);
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Команда (необязательно)
        <select className={fieldClass} value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">—</option>
          {Object.keys(TEAM_LABELS).map((t) => (
            <option key={t} value={t}>
              {label(TEAM_LABELS, t)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-1 flex-col gap-1 text-xs text-gray-500">
        Причина (необязательно)
        <input className={fieldClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <button
        type="submit"
        className="rounded bg-gray-900 px-3 py-1 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        disabled={pending}
      >
        {submitLabel}
      </button>
    </form>
  );
}

function NoteForm({
  pending,
  fieldLabel,
  submitLabel,
  onSubmit,
}: {
  pending: boolean;
  fieldLabel: string;
  submitLabel: string;
  onSubmit: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded bg-gray-50 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(note.trim());
      }}
    >
      <label className="flex flex-1 flex-col gap-1 text-xs text-gray-500">
        {fieldLabel}
        <input className={fieldClass} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <button
        type="submit"
        className="rounded bg-gray-900 px-3 py-1 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        disabled={pending}
      >
        {submitLabel}
      </button>
    </form>
  );
}
