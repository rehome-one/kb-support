"use client";

import { useState } from "react";

import type { CaseStateTransitionInput, DecisionInput } from "@/lib/api/client";

import { CASE_STATE_LABELS, DECISION_LABELS, label } from "../format";
import type { ActionResult, Ticket } from "./types";

interface Props {
  ticket: Ticket;
  decideAction: (id: string, input: DecisionInput) => Promise<ActionResult>;
  transitionCaseStateAction: (id: string, input: CaseStateTransitionInput) => Promise<ActionResult>;
}

const fieldClass = "rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50";

// Вердикты, требующие суммы (FR-9.6: approved_amount обязателен при FULL/PARTIAL).
const NEEDS_AMOUNT: ReadonlySet<string> = new Set(["FULL", "PARTIAL"]);
// Вердикты, требующие мотивировки (reason обязателен при PARTIAL/REJECTED).
const NEEDS_REASON: ReadonlySet<string> = new Set(["PARTIAL", "REJECTED"]);

export function ClaimActions({ ticket, decideAction, transitionCaseStateAction }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ status: number; title: string } | null>(null);

  // Единая точка запуска мутации (как в TicketActions): pending + сброс ошибки + результат.
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

  // Переходы отдаёт бэкенд (allowed_case_transitions, #231) — фронт НЕ дублирует машину.
  // Пусто = терминал ИЛИ case_state ещё не присвоен (claims без состояния) — оба случая
  // корректно дают «нет доступных переходов» без падения.
  const allowedCase = ticket.allowed_case_transitions ?? [];
  const decided = ticket.decision != null;

  return (
    <section
      className="flex flex-col gap-4 rounded border border-gray-200 p-4"
      aria-label="Действия по претензии"
    >
      <h2 className="text-lg font-semibold">Действия по претензии</h2>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error.title}
        </div>
      )}

      <CaseStateForm
        pending={pending}
        allowed={allowedCase}
        onSubmit={(input) => dispatch(() => transitionCaseStateAction(ticket.id, input))}
      />

      <div className="flex flex-col gap-2 border-t pt-3">
        <h3 className="text-xs font-medium text-gray-500">Решение</h3>
        {decided ? (
          // Решение принимается один раз (повтор → 409). Принятое показываем в ClaimPanel;
          // здесь форму скрываем, чтобы не провоцировать конфликт.
          <p className="text-sm text-gray-500">
            Решение уже принято: {label(DECISION_LABELS, ticket.decision)}.
          </p>
        ) : (
          <DecisionForm
            pending={pending}
            onSubmit={(input) => dispatch(() => decideAction(ticket.id, input))}
          />
        )}
      </div>
    </section>
  );
}

function CaseStateForm({
  pending,
  allowed,
  onSubmit,
}: {
  pending: boolean;
  allowed: Ticket["allowed_case_transitions"];
  onSubmit: (input: CaseStateTransitionInput) => void;
}) {
  const options = allowed ?? [];
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");

  if (options.length === 0) {
    return (
      <div className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-gray-500">Состояние разбирательства</h3>
        <p className="text-sm text-gray-400">Нет доступных переходов состояния.</p>
      </div>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!target) return;
        const input: CaseStateTransitionInput = {
          case_state: target as CaseStateTransitionInput["case_state"],
        };
        if (note.trim()) input.note = note.trim();
        onSubmit(input);
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Новое состояние
        <select
          className={fieldClass}
          disabled={pending}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        >
          <option value="">— выбрать —</option>
          {options.map((s) => (
            <option key={s} value={s}>
              {label(CASE_STATE_LABELS, s)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-1 flex-col gap-1 text-xs text-gray-500">
        Комментарий (необязательно)
        <input className={fieldClass} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <button
        type="submit"
        className="rounded bg-gray-900 px-3 py-1 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        disabled={pending || !target}
      >
        Сменить состояние
      </button>
    </form>
  );
}

function DecisionForm({
  pending,
  onSubmit,
}: {
  pending: boolean;
  onSubmit: (input: DecisionInput) => void;
}) {
  const [decision, setDecision] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");

  // Клиент-хинты обязательности (зеркало доменных правил FR-9.6) — истина за бэкендом (422).
  const needsAmount = NEEDS_AMOUNT.has(decision);
  const needsReason = NEEDS_REASON.has(decision);
  const blocked =
    pending ||
    !decision ||
    (needsAmount && amount.trim() === "") ||
    (needsReason && reason.trim() === "");

  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded bg-gray-50 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!decision) return;
        const input: DecisionInput = { decision: decision as DecisionInput["decision"] };
        if (amount.trim() !== "") input.approved_amount = Number(amount);
        if (reason.trim() !== "") input.reason = reason.trim();
        onSubmit(input);
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Вердикт
        <select
          className={fieldClass}
          disabled={pending}
          value={decision}
          onChange={(e) => {
            // Сброс зависимых полей при смене вердикта — иначе стейл-значение (напр. сумма,
            // введённая для FULL) ушло бы с REJECTED. Обязательность пересчитывается ниже.
            setDecision(e.target.value);
            setAmount("");
            setReason("");
          }}
        >
          <option value="">— выбрать —</option>
          {Object.keys(DECISION_LABELS).map((d) => (
            <option key={d} value={d}>
              {label(DECISION_LABELS, d)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Одобренная сумма{needsAmount ? " *" : " (необязательно)"}
        <input
          type="number"
          min="0"
          step="0.01"
          className={fieldClass}
          disabled={pending}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </label>
      <label className="flex flex-1 flex-col gap-1 text-xs text-gray-500">
        Мотивировка{needsReason ? " *" : " (необязательно)"}
        <input
          className={fieldClass}
          disabled={pending}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <button
        type="submit"
        className="rounded bg-gray-900 px-3 py-1 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        disabled={blocked}
      >
        Зафиксировать решение
      </button>
    </form>
  );
}
